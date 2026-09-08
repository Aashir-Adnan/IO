from __future__ import annotations

import io
import shutil
import subprocess
import wave

from io_assistant.config import Config
from io_assistant.speak.interface import SpeakError
from io_assistant.speak.text import flatten_markdown

__all__ = ["PiperSpeaker"]


class PiperSpeaker:
    def __init__(self, config: Config):
        self._cfg = config.voice
        self._voice_path = config.voice.resolved_voice_path

    def _check_voice(self) -> None:
        if not self._voice_path.exists():
            raise SpeakError(
                f"Piper voice not found: {self._voice_path}\n"
                f"Download it, e.g.: python -m piper.download_voices "
                f"{self._cfg.tts_voice} --data-dir {self._voice_path.parent}"
            )

    def synthesize(self, text: str) -> bytes:
        self._check_voice()
        prose = flatten_markdown(text) or "Nothing to say."
        try:
            from piper import PiperVoice  # type: ignore
        except ImportError:
            PiperVoice = None
        if PiperVoice is not None:
            voice = PiperVoice.load(str(self._voice_path))
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                voice.synthesize_wav(prose, wf)
            return buf.getvalue()

        binary = self._cfg.piper_bin or shutil.which("piper")
        if not binary:
            raise SpeakError(
                "Piper not available: install `piper-tts` or put a `piper` "
                "binary on PATH (or set [voice].piper_bin)."
            )
        proc = subprocess.run(
            [binary, "--model", str(self._voice_path), "--output_file", "-"],
            input=prose.encode(),
            capture_output=True,
        )
        if proc.returncode != 0:
            raise SpeakError(f"piper failed: {proc.stderr.decode()[:200]}")
        return proc.stdout

    def say(self, text: str) -> None:
        data = self.synthesize(text)
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as e:  # pragma: no cover
            raise SpeakError(f"audio playback unavailable: {e}") from e
        with wave.open(io.BytesIO(data), "rb") as wf:
            rate = wf.getframerate()
            frames = wf.readframes(wf.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16)
        try:
            sd.play(audio, rate)
            sd.wait()
        except Exception as e:  # pragma: no cover - needs an output device
            raise SpeakError(f"playback failed: {e}") from e
