from __future__ import annotations

from datetime import datetime
from importlib import resources

from io_assistant.config import Config
from io_assistant.models_domain import ExtractionResult, Intent, AnswerShape
from io_assistant.extract.schema import SCHEMA_JSON, FEWSHOT
from io_assistant.backend.interface import BackendParseError


class AnthropicBackendError(Exception):
    pass


_INTENTS = {"STORE": "store", "QUERY": "query", "UNKNOWN": "unknown"}


def _prompt(name: str) -> str:
    return resources.files("io_assistant.prompts").joinpath(name).read_text()


class AnthropicBackend:
    def __init__(self, config: Config, client=None):
        self._model = config.backend.anthropic_model
        if client is None:
            import anthropic
            client = anthropic.Anthropic()
        self._client = client

    def _complete(self, system: str, user: str) -> str:
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=2048,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            raise AnthropicBackendError(str(e)) from e
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip()

    def route(self, utterance: str) -> Intent:
        out = self._complete(
            "You are a precise classifier. Reply with one word.",
            _prompt("route.txt").format(utterance=utterance)
        )
        token = out.upper().split()[0] if out else ""
        return _INTENTS.get(token, "unknown")

    def extract(self, utterance: str, now: datetime) -> ExtractionResult:
        user = _prompt("extract.txt").format(
            schema=SCHEMA_JSON,
            examples=FEWSHOT,
            now=now.isoformat(),
            utterance=utterance
        )
        out = self._complete(
            "You extract structured data. Output a single JSON object and nothing else.",
            user
        )
        # tolerate ```json fences
        out = out.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return ExtractionResult.model_validate_json(out)
        except Exception as e:
            raise BackendParseError(str(e)) from e

    def plan(self, question: str, now: datetime) -> dict:
        raise NotImplementedError("Plan 2")

    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str:
        raise NotImplementedError("Plan 2")
