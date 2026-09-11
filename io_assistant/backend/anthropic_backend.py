from __future__ import annotations

import json
from datetime import datetime
from importlib import resources

from io_assistant.config import Config
from io_assistant.models_domain import ExtractionResult, Intent, AnswerShape, Plan
from io_assistant.extract.schema import SCHEMA_JSON, FEWSHOT
from io_assistant.actions.registry import describe_capabilities
from io_assistant.decide.parse import parse_plan
from io_assistant.backend.interface import BackendParseError, render_context


class AnthropicBackendError(Exception):
    pass


_INTENTS = {"STORE": "store", "QUERY": "query", "FILE": "file", "UNKNOWN": "unknown"}


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

    def route(self, utterance: str, *, context: str | None = None) -> Intent:
        out = self._complete(
            "You are a precise classifier. Reply with one word.",
            _prompt("route.txt").format(
                context=render_context(context), utterance=utterance
            ),
            max_tokens=16,
        )
        token = out.upper().split()[0] if out else ""
        return _INTENTS.get(token, "unknown")

    def extract(self, utterance: str, now: datetime, *, context: str | None = None) -> ExtractionResult:
        system = [{
            "type": "text",
            "text": _EXTRACT_SYSTEM,
            "cache_control": {"type": "ephemeral"},
        }]
        user = (
            f'Assume "now" is {now.isoformat()}.\n'
            f"{render_context(context)}"
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

    def decide(self, utterance: str, now: datetime, *, context: str | None = None,
               files_enabled: bool = False, web_enabled: bool = False) -> Plan:
        caps = describe_capabilities(
            files_enabled=files_enabled, web_enabled=web_enabled
        ) or "  (none)"
        system = [{
            "type": "text",
            "text": (
                "You are IO's turn planner. Output one JSON object and nothing "
                "else.\n\nCapabilities:\n" + caps + "\n\nEXTRACTION schema:\n" + SCHEMA_JSON
            ),
            "cache_control": {"type": "ephemeral"},
        }]
        user = _prompt("decide.txt").format(
            capabilities=caps, schema="(see system)",
            context=render_context(context), now=now.isoformat(), utterance=utterance,
        )
        out = self._complete(system, user, max_tokens=1200)
        return parse_plan(out, files_enabled=files_enabled)

    def plan(
        self, question: str, now: datetime, *, context: str | None = None
    ) -> dict:
        out = self._complete(
            "You convert a question into a retrieval plan. Output one JSON "
            "object and nothing else.",
            _prompt("plan.txt").format(
                context=render_context(context),
                now=now.isoformat(), question=question,
            ),
            max_tokens=512,
        )
        out = (
            out.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        try:
            data = json.loads(out)
        except (json.JSONDecodeError, TypeError) as e:
            raise BackendParseError(str(e)) from e
        if not isinstance(data, dict):
            raise BackendParseError(f"plan is not an object: {out!r}")
        return data

    def phrase(
        self, question: str, rows: list[dict], shape: AnswerShape,
        *, context: str | None = None,
    ) -> str:
        return self._complete(
            "You answer strictly from the provided rows.",
            _prompt("respond.txt").format(
                context=render_context(context),
                question=question,
                rows=json.dumps(rows, default=str),
                shape=shape,
            ),
            max_tokens=800,
        )

    def acknowledge(self, facts: str, *, context: str | None = None) -> str:
        return self._complete(
            "You confirm saved items as a calm personal assistant.",
            _prompt("acknowledge.txt").format(
                context=render_context(context), facts=facts
            ),
            max_tokens=120,
        )

    def summarize_file(self, title: str, head_text: str, *,
                       mime: str | None = None) -> dict:
        out = self._complete(
            "You summarise a file into one JSON object. Output JSON only.",
            _prompt("file_summary.txt").format(
                title=title or "(untitled)", mime=mime or "unknown",
                head=head_text[:6000],
            ),
            max_tokens=300,
        )
        out = out.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        if "{" in out and "}" in out:
            out = out[out.index("{"): out.rindex("}") + 1]
        try:
            data = json.loads(out)
        except (json.JSONDecodeError, TypeError) as e:
            raise BackendParseError(str(e)) from e
        if not isinstance(data, dict):
            raise BackendParseError(f"summary is not an object: {out!r}")
        return {
            "summary": str(data.get("summary") or "")[:400],
            "names": [str(x) for x in (data.get("names") or []) if str(x).strip()],
            "references": [str(x) for x in (data.get("references") or []) if str(x).strip()],
        }

    def answer_from_files(self, question: str, files: list[dict], shape: str,
                          *, context: str | None = None) -> str:
        blocks = []
        for f in files:
            ex = "\n".join(f"  - {e}" for e in f.get("excerpts", []))
            blocks.append(
                f"[{f.get('path')}] {f.get('title') or ''}\n"
                f"  summary: {f.get('summary') or ''}\n{ex}"
            )
        return self._complete(
            "You answer strictly from the provided files.",
            _prompt("file_answer.txt").format(
                context=render_context(context), question=question,
                files="\n\n".join(blocks), shape=shape,
            ),
            max_tokens=500,
        )
