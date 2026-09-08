from __future__ import annotations

from io_assistant.service.schemas import UtteranceIn

__all__ = ["build_utterance"]


def build_utterance(
    text: str, confidence: float | None, source: str = "voice"
) -> UtteranceIn:
    cleaned = (text or "").strip()
    if not cleaned:
        raise ValueError("empty transcript")
    return UtteranceIn(text=cleaned, source=source)
