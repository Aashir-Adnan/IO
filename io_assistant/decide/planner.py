"""Turn an utterance into a `Plan` — an ordered list of `Step`s.

Two modes:

- **split**  — call the existing `Router` + `Extractor` and assemble a single
  step. Mirrors the historical `route` → (`extract`) behaviour exactly.
- **combined** — one `backend.decide` call that returns the whole Plan
  (possibly several steps, incl. `action` steps). Any parse failure falls back
  to split, so a bad model response can never break a turn.

`[backend].decide` picks: "split" / "combined" force it; "auto" (default) uses
combined on anthropic / hybrid backends and on local "quality", split on local
"light" (small models are brittle with the big combined prompt).

See docs/superpowers/specs/2026-09-09-unified-decide-pipeline-design.md.
"""
from __future__ import annotations

from datetime import datetime

from io_assistant.backend.interface import BackendParseError
from io_assistant.extract.extractor import Extractor
from io_assistant.models_domain import Plan, Step
from io_assistant.route.router import Router

__all__ = ["DecidePlanner"]


class DecidePlanner:
    def __init__(self, backend, config=None):
        self._backend = backend
        self._config = config
        self._router = Router(backend)
        self._extractor = Extractor(backend)
        self._mode = self._resolve_mode(config)

    @staticmethod
    def _resolve_mode(config) -> str:
        if config is None:
            return "split"
        setting = getattr(config.backend, "decide", "auto")
        if setting in ("split", "combined"):
            return setting
        # auto
        if config.backend.provider in ("anthropic", "hybrid"):
            return "combined"
        if config.backend.provider == "local" and config.backend.profile == "quality":
            return "combined"
        return "split"

    def plan(self, text: str, now: datetime, *, context: str | None = None) -> Plan:
        if not text or not text.strip():
            return Plan(steps=[Step(kind="unknown")])

        if self._mode == "combined" and hasattr(self._backend, "decide"):
            try:
                return self._combined(text, now, context=context)
            except (BackendParseError, NotImplementedError, AttributeError):
                pass   # fall through to split
            except Exception:  # noqa: BLE001 - a backend/network error also falls back
                pass

        return self._split(text, now, context=context)

    def _split(self, text: str, now: datetime, *, context: str | None) -> Plan:
        intent = self._router.classify(text, context=context)
        if intent == "unknown":
            return Plan(steps=[Step(kind="unknown")])
        if intent == "query":
            return Plan(steps=[Step(kind="query", question=text)])
        if intent == "file":
            return Plan(steps=[Step(kind="file", question=text)])
        return Plan(steps=[Step(kind="store", extraction=self._extractor.run(text, now, context=context))])

    def _combined(self, text: str, now: datetime, *, context: str | None) -> Plan:
        files_enabled = bool(
            self._config and getattr(self._config.files, "enabled", False)
        )
        web_enabled = bool(
            self._config and getattr(getattr(self._config, "web", None), "enabled", False)
        )
        plan = self._backend.decide(text, now, context=context,
                                    files_enabled=files_enabled, web_enabled=web_enabled)
        # scrub role-noun "people" out of any store step, same as split mode
        from io_assistant.extract.scrub import scrub_roles
        for step in plan.steps:
            if step.kind == "store" and step.extraction is not None:
                step.extraction = scrub_roles(step.extraction)
        return plan if plan.steps else Plan(steps=[Step(kind="unknown")])
