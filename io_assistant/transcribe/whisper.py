from __future__ import annotations

import math

from io_assistant.config import Config, whisper_model_for
from io_assistant.transcribe.interface import Transcript, TranscribeError

__all__ = ["WhisperTranscriber"]


def _pick_device() -> tuple[str, str]:
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "int8_float16"
    except Exception:
        pass
    return "cpu", "int8"


class WhisperTranscriber:
    def __init__(self, config: Config):
        self._size = whisper_model_for(config.backend.profile)
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise TranscribeError(
                    "faster-whisper not installed (`uv add faster-whisper`)."
                ) from e
            device, compute = _pick_device()
            self._model = WhisperModel(self._size, device=device, compute_type=compute)
        return self._model

    def transcribe(self, wav_path: str) -> Transcript:
        model = self._load()
        try:
            segments, _info = model.transcribe(wav_path, vad_filter=True)
            segs = list(segments)
        except Exception as e:  # noqa: BLE001
            raise TranscribeError(str(e)) from e
        text = " ".join(s.text.strip() for s in segs).strip()
        if segs:
            avg = sum(getattr(s, "avg_logprob", -1.0) for s in segs) / len(segs)
            conf = max(0.0, min(1.0, math.exp(avg)))
        else:
            conf = None
        return Transcript(text=text, confidence=conf)
