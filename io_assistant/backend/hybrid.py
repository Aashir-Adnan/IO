from __future__ import annotations

from datetime import datetime

from io_assistant.backend.interface import Backend
from io_assistant.models_domain import AnswerShape, ExtractionResult, Intent


class HybridBackend:
    def __init__(self, local: Backend, cloud: Backend):
        self._local = local
        self._cloud = cloud

    def route(self, utterance: str) -> Intent:
        return self._local.route(utterance)

    def extract(self, utterance: str, now: datetime) -> ExtractionResult:
        return self._cloud.extract(utterance, now)

    def plan(self, question: str, now: datetime) -> dict:
        return self._cloud.plan(question, now)

    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str:
        return self._cloud.phrase(question, rows, shape)
