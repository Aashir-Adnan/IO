from __future__ import annotations

from datetime import datetime

from io_assistant.backend.interface import Backend
from io_assistant.models_domain import AnswerShape, ExtractionResult, Intent


class HybridBackend:
    def __init__(self, local: Backend, cloud: Backend):
        self._local = local
        self._cloud = cloud

    def route(self, utterance: str, *, context: str | None = None) -> Intent:
        return self._local.route(utterance, context=context)

    def extract(self, utterance: str, now: datetime) -> ExtractionResult:
        return self._cloud.extract(utterance, now)

    def plan(
        self, question: str, now: datetime, *, context: str | None = None
    ) -> dict:
        return self._cloud.plan(question, now, context=context)

    def phrase(
        self, question: str, rows: list[dict], shape: AnswerShape,
        *, context: str | None = None,
    ) -> str:
        return self._cloud.phrase(question, rows, shape, context=context)

    def acknowledge(self, facts: str, *, context: str | None = None) -> str:
        return self._cloud.acknowledge(facts, context=context)

    def summarize_file(self, title: str, head_text: str, *,
                       mime: str | None = None) -> dict:
        return self._local.summarize_file(title, head_text, mime=mime)

    def answer_from_files(self, question: str, files: list[dict], shape: str,
                          *, context: str | None = None) -> str:
        return self._cloud.answer_from_files(question, files, shape, context=context)
