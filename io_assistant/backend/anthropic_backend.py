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


def _make_client():
    """Build the Anthropic client.

    Supports both a plain API key (``ANTHROPIC_API_KEY``) and a Claude
    subscription OAuth token (``ANTHROPIC_AUTH_TOKEN``, e.g. from
    ``claude setup-token``). An OAuth token is sent as a bearer credential and
    needs the oauth beta header; an API key uses the SDK's normal resolution.
    """
    import os

    import anthropic

    token = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    if token and not os.environ.get("ANTHROPIC_API_KEY"):
        return anthropic.Anthropic(
            auth_token=token,
            default_headers={"anthropic-beta": "oauth-2025-04-20"},
        )
    return anthropic.Anthropic()


def _prompt(name: str) -> str:
    return resources.files("io_assistant.prompts").joinpath(name).read_text()


# The extraction schema and few-shot block are identical on every call, so they
# ride in a cached system block (Anthropic prompt caching) instead of being
# re-sent as fresh input tokens each time. Only "now" + the utterance vary.
_EXTRACT_SYSTEM = (
    "You extract structured data. Output a single JSON object and nothing else.\n\n"
    + SCHEMA_JSON
    + "\n\nExamples (one INPUT sentence and its OUTPUT JSON - describe only the "
    "sentence, never copy an example):\n"
    + FEWSHOT
)


class AnthropicBackend:
    def __init__(self, config: Config, client=None):
        self._model = config.backend.anthropic_model
        if client is None:
            client = _make_client()
        self._client = client

    def _complete(self, system, user: str, *, max_tokens: int) -> str:
        try:
            msg = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
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
            _prompt("route.txt").format(utterance=utterance),
            max_tokens=16,
        )
        token = out.upper().split()[0] if out else ""
        return _INTENTS.get(token, "unknown")

    def extract(self, utterance: str, now: datetime) -> ExtractionResult:
        system = [{
            "type": "text",
            "text": _EXTRACT_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }]
        user = (
            f'Assume "now" is {now.isoformat()}.\n'
            "Produce the OUTPUT JSON for THIS input only.\n"
            f"INPUT: {utterance}\nOUTPUT:"
        )
        out = self._complete(system, user, max_tokens=1024)
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
