from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["Transcript", "Transcriber", "TranscribeError"]


class TranscribeError(Exception):
    pass


@dataclass
class Transcript:
    text: str
    confidence: float | None = None


@runtime_checkable
class Transcriber(Protocol):
    def transcribe(self, wav_path: str) -> Transcript: ...
