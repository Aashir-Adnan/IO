from __future__ import annotations

import base64
import io
import sys
import tempfile
import wave

__all__ = ["VoiceLoop"]


class VoiceLoop:
    """Local capture + playback around the service's POST /voice. Transcription
    and synthesis happen server-side."""

    def __init__(self, config, *, client):
        self._cfg = config
        self._client = client
        self._rate = config.capture.sample_rate
        self._conversation_id = None

    def handle_wav(self, wav_path: str) -> str:
        with open(wav_path, "rb") as f:
            wav = f.read()
        try:
            reply = self._client.send_voice(
                wav, conversation_id=self._conversation_id,
                speak=self._cfg.ui.auto_speak != "never",
            )
        except Exception as e:  # noqa: BLE001
            print(f"[voice] turn failed: {e}", file=sys.stderr)
            return ""
        self._conversation_id = reply.get("conversation_id", self._conversation_id)
        if reply.get("transcript"):
            print(f"you: {reply['transcript']}")
        print(f"io: {reply.get('text', '')}")
        if reply.get("audio_b64"):
            self._play(reply["audio_b64"])
        return reply.get("text", "")

    def _play(self, audio_b64: str) -> None:  # pragma: no cover - needs a device
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError:
            return
        with wave.open(io.BytesIO(base64.b64decode(audio_b64)), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
        try:
            sd.play(np.frombuffer(frames, dtype=np.int16), rate)
            sd.wait()
        except Exception as e:
            print(f"[voice] playback failed: {e}", file=sys.stderr)

    def _pcm_to_wav(self, pcm: bytes) -> str:
        path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._rate)
            wf.writeframes(pcm)
        return path

    def run_push_to_talk(self) -> None:  # pragma: no cover - needs a keyboard
        import threading

        from io_assistant.capture.audio import record_until
        from io_assistant.capture.hotkey import push_to_talk

        print(
            f"Press {self._cfg.capture.hotkey} to start, again to stop. "
            "Ctrl-C to quit."
        )
        stop = threading.Event()
        state: dict = {"thread": None}

        def on_press():
            stop.clear()
            state["thread"] = threading.Thread(
                target=lambda: state.__setitem__(
                    "pcm", record_until(stop, rate=self._rate)
                )
            )
            state["thread"].start()

        def on_release():
            stop.set()
            if state["thread"]:
                state["thread"].join()
            self.handle_wav(self._pcm_to_wav(state.pop("pcm", b"")))

        listener = push_to_talk(self._cfg.capture.hotkey, on_press, on_release)
        try:
            listener.join()
        except KeyboardInterrupt:
            listener.stop()

    def run_passive(self) -> None:  # pragma: no cover - needs a microphone
        import numpy as np
        import sounddevice as sd

        from io_assistant.capture.vad import segment_stream

        print("Passive mode - everything you say is routed. Ctrl-C to quit.")
        frame = int(self._rate * 0.03)

        def frames():
            with sd.InputStream(
                samplerate=self._rate, channels=1, dtype="int16"
            ) as st:
                while True:
                    data, _ = st.read(frame)
                    yield np.asarray(data, dtype="int16").tobytes()

        try:
            for seg in segment_stream(
                frames(),
                rate=self._rate,
                aggressiveness=self._cfg.capture.vad_aggressiveness,
            ):
                self.handle_wav(self._pcm_to_wav(seg))
        except KeyboardInterrupt:
            return
