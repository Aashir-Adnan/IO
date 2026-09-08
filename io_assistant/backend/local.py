from __future__ import annotations

import os
from datetime import datetime
from importlib import resources

import httpx

from io_assistant.config import Config
from io_assistant.models_domain import AnswerShape, ExtractionResult, Intent
from io_assistant.extract.schema import SCHEMA_JSON, FEWSHOT  # Task 8 provides these

from io_assistant.backend.interface import BackendParseError  # single shared class

__all__ = ["LocalBackend", "LocalBackendError", "BackendParseError"]


class LocalBackendError(Exception):
    pass


_INTENTS = {"STORE": "store", "QUERY": "query", "UNKNOWN": "unknown"}


def _load_prompt(name: str) -> str:
    return resources.files("io_assistant.prompts").joinpath(name).read_text()


def _resolve_threads(n: int) -> int:
    if n and n > 0:
        return n
    return max(1, (os.cpu_count() or 4) - 2)


class LocalBackend:
    def __init__(self, config: Config):
        self._url = config.backend.ollama_url.rstrip("/") + "/api/chat"
        self._model = config.backend.instruct_model
        self._keep_alive = config.backend.ollama_keep_alive
        self._num_thread = _resolve_threads(config.backend.num_thread)

    def _chat(self, system: str, user: str, *, json_mode: bool) -> str:
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {"num_thread": self._num_thread, "temperature": 0},
        }
        if json_mode:
            body["format"] = "json"
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(self._url, json=body)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise LocalBackendError(f"ollama chat failed: {e}") from e
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as e:
            raise LocalBackendError(
                f"ollama chat returned an unexpected body: {data!r}"
            ) from e

    def route(self, utterance: str) -> Intent:
        out = self._chat(
            "You are a precise classifier.",
            _load_prompt("route.txt").format(utterance=utterance),
            json_mode=False,
        )
        token = out.strip().upper().split()[0] if out.strip() else ""
        return _INTENTS.get(token, "unknown")

    def extract(self, utterance: str, now: datetime) -> ExtractionResult:
        prompt = _load_prompt("extract.txt").format(
            schema=SCHEMA_JSON,
            examples=FEWSHOT,
            now=now.isoformat(),
            utterance=utterance,
        )
        out = self._chat(
            "You are an information-extraction function. For the single INPUT "
            "sentence, output ONE JSON object about THAT sentence only. Never "
            "copy the examples. Output JSON only.",
            prompt, json_mode=True
        )
        try:
            return ExtractionResult.model_validate_json(out)
        except Exception as e:
            raise BackendParseError(str(e)) from e

    def plan(self, question: str, now: datetime) -> dict:
        raise NotImplementedError("Plan 2")

    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str:
        raise NotImplementedError("Plan 2")
