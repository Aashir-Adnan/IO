from __future__ import annotations

import sys
import tempfile
import wave

from io_assistant.capture.session import build_utterance
from io_assistant.speak.interface import SpeakError

__all__ = ["VoiceLoop"]


class VoiceLoop:
    def __init__(self, config, *, transcriber, speaker, client):
        self._cfg = config
        self._t = transcriber
        self._s = speaker
        self._client = client
        self._rate = config.capture.sample_rate

    def handle_wav(self, wav_path: str) -> str:
        tr = self._t.transcribe(wav_path)
        try:
            u = build_utterance(tr.text, tr.confidence)
        except ValueError:
            return ""
        reply = self._client.send(u)
        try:
            self._s.say(reply.message)
        except SpeakError as e:
            print(f"[voice] speech output unavailable: {e}", file=sys.stderr)
        return reply.message

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

        print("Passive mode — everything you say is routed. Ctrl-C to quit.")
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
