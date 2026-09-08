from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from io_assistant.models_domain import AnswerShape, ExtractionResult, Intent

__all__ = ["Backend", "BackendParseError", "render_context"]


class BackendParseError(Exception):
    """Raised by any backend when the model's extract output can't be parsed
    into an ExtractionResult. Single shared class; re-exported by local.py and
    anthropic_backend.py."""


def render_context(context: str | None) -> str:
    """Prompt fragment for the recent-conversation block. Empty when no context."""
    return f"Recent conversation:\n{context}\n\n" if context else ""


@runtime_checkable
class Backend(Protocol):
    def route(self, utterance: str, *, context: str | None = None) -> Intent: ...

    def extract(self, utterance: str, now: datetime) -> ExtractionResult: ...

    def plan(
        self, question: str, now: datetime, *, context: str | None = None
    ) -> dict:
        """Return the model's retrieval plan as a parsed JSON object (dict).
        Grounding/clamping happens in io_assistant.query.plan.ground_plan.
        Raise BackendParseError if the output is not a JSON object."""
        ...

    def phrase(
        self, question: str, rows: list[dict], shape: AnswerShape,
        *, context: str | None = None,
    ) -> str: ...

    def acknowledge(self, facts: str, *, context: str | None = None) -> str:
        """One natural sentence confirming what persist_store just wrote.
        `facts` is a plain-text list built from the written rows — the model
        only restates it, never adds or decides."""
        ...

    def summarize_file(self, title: str, head_text: str, *,
                       mime: str | None = None) -> dict:
        """One-time file summary for the index. Returns
        {"summary": str, "names": [str], "references": [str]}. Every part is
        deterministically validated before use (names → resolve_query_entities,
        references → path match). Raises BackendParseError on bad JSON."""
        ...

    def answer_from_files(self, question: str, files: list[dict], shape: str,
                          *, context: str | None = None) -> str:
        """Phrase an answer strictly from the supplied file material.
        `files` entries: {"path","title","summary","excerpts": [str]}."""
        ...
