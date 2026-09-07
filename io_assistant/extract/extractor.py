from __future__ import annotations

from datetime import datetime

from io_assistant.backend.interface import Backend, BackendParseError
from io_assistant.models_domain import ExtractionResult


class Extractor:
    def __init__(self, backend: Backend):
        self._backend = backend

    def run(self, utterance: str, now: datetime) -> ExtractionResult | None:
        for attempt in (1, 2):
            try:
                return self._backend.extract(utterance, now)
            except BackendParseError:
                if attempt == 2:
                    return None
        return None
