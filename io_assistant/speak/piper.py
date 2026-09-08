from __future__ import annotations

import io
import shutil
import subprocess
import wave

from io_assistant.config import Config
from io_assistant.speak.interface import SpeakError
from io_assistant.speak.speech_text import prep_for_speech, split_sentences

__all__ = ["PiperSpeaker"]

_GAP_SENTENCE = 0.18   # seconds of silence after . ? !
_GAP_CLAUSE = 0.12     # after , ; :


def _gap_after(sentence: str) -> float:
    return _GAP_SENTENCE if sentence.rstrip().endswith((".", "?", "!")) else _GAP_CLAUSE


class PiperSpeaker:
    def __init__(self, config: Config):
        self._cfg = config.voice
        self._voice_path = config.voice.resolved_voice_path
        self._voice = None  # cached PiperVoice

    def _check_voice(self) -> None:
        if not self._voice_path.exists():
            raise SpeakError(
                f"Piper voice not found: {self._voice_path}\n"
                f"Download it, e.g.: python -m piper.download_voices "
                f"{self._cfg.tts_voice} --data-dir {self._voice_path.parent}"
            )

    def _syn_config(self):
        try:
            from piper import SynthesisConfig  # type: ignore
        except Exception:
            return None
        return SynthesisConfig(
            length_scale=self._cfg.length_scale,
            noise_scale=self._cfg.noise_scale,
            noise_w_scale=self._cfg.noise_w_scale,
        )

    def _load_voice(self):
        if self._voice is None:
            from piper import PiperVoice  # type: ignore

            self._voice = PiperVoice.load(str(self._voice_path))
        return self._voice

    def _one_sentence_wav(self, sentence: str) -> bytes:
        try:
            from piper import PiperVoice  # noqa: F401  (presence check)
            have_pkg = True
        except ImportError:
            have_pkg = False

        if have_pkg:
            voice = self._load_voice()
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                cfg = self._syn_config()
                if cfg is not None:
                    voice.synthesize_wav(sentence, wf, syn_config=cfg)
                else:
                    voice.synthesize_wav(sentence, wf)
            return buf.getvalue()

        binary = self._cfg.piper_bin or shutil.which("piper")
        if not binary:
            raise SpeakError(
                "Piper not available: install `piper-tts` or put a `piper` "
                "binary on PATH (or set [voice].piper_bin)."
            )
        proc = subprocess.run(
            [binary, "--model", str(self._voice_path), "--output_file", "-"],
            input=sentence.encode(),
            capture_output=True,
        )
        if proc.returncode != 0:
            raise SpeakError(f"piper failed: {proc.stderr.decode()[:200]}")
        return proc.stdout

    def synthesize(self, text: str) -> bytes:
        self._check_voice()
        prose = prep_for_speech(text)
        sentences = split_sentences(prose)
        if not sentences:
            return _silent_wav(22050, 1)

        rate = None
        width = 2
        chans = 1
        pcm = bytearray()
        for i, sentence in enumerate(sentences):
            data = self._one_sentence_wav(sentence)
            with wave.open(io.BytesIO(data), "rb") as wf:
                if rate is None:
                    rate, width, chans = wf.getframerate(), wf.getsampwidth(), wf.getnchannels()
                pcm += wf.readframes(wf.getnframes())
            if i < len(sentences) - 1:
                pcm += b"\x00" * int(rate * _gap_after(sentence)) * width * chans

        out = io.BytesIO()
        with wave.open(out, "wb") as wf:
            wf.setnchannels(chans)
            wf.setsampwidth(width)
            wf.setframerate(rate)
            wf.writeframes(bytes(pcm))
        return out.getvalue()

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


def _silent_wav(rate: int, frames: int) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x00\x00" * frames)
    return out.getvalue()
