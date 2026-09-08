from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["Speaker", "SpeakError"]


class SpeakError(Exception):
    pass


@runtime_checkable
class Speaker(Protocol):
    def say(self, text: str) -> None: ...
    def synthesize(self, text: str) -> bytes: ...
