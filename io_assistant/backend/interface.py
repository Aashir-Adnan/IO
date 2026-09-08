from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from io_assistant.models_domain import AnswerShape, ExtractionResult, Intent


class BackendParseError(Exception):
    """Raised by any backend when the model's extract output can't be parsed
    into an ExtractionResult. Single shared class; re-exported by local.py and
    anthropic_backend.py."""


@runtime_checkable
class Backend(Protocol):
    def route(self, utterance: str) -> Intent: ...

    def extract(self, utterance: str, now: datetime) -> ExtractionResult: ...

    def plan(self, question: str, now: datetime) -> dict:
        """Return the model's retrieval plan as a parsed JSON object (dict).
        Grounding/clamping happens in io_assistant.query.plan.ground_plan.
        Raise BackendParseError if the output is not a JSON object."""
        ...

    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str: ...
