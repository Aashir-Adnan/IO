"""Parse a model's `decide` JSON into a validated `Plan`.

Tolerant: unknown step kinds / bad extractions / unknown action slugs are
dropped rather than raising, so a partly-good response still yields a usable
plan. A completely unusable response raises BackendParseError so the planner
falls back to split mode.
"""
from __future__ import annotations

import json

from io_assistant.actions.registry import validate_action
from io_assistant.backend.interface import BackendParseError
from io_assistant.models_domain import ExtractionResult, Plan, Step

__all__ = ["parse_plan"]

_KINDS = {"store", "query", "file", "action", "unknown"}


def _strip_fences(raw: str) -> str:
    s = (raw or "").strip()
    s = s.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    if "{" in s and "}" in s:
        s = s[s.index("{"): s.rindex("}") + 1]
    return s


def parse_plan(raw: str, *, files_enabled: bool) -> Plan:
    try:
        data = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, TypeError) as e:
        raise BackendParseError(f"decide: not JSON ({e})") from e
    if not isinstance(data, dict):
        raise BackendParseError("decide: top level is not an object")

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise BackendParseError("decide: no steps")

    steps: list[Step] = []
    for rs in raw_steps:
        if not isinstance(rs, dict):
            continue
        kind = str(rs.get("kind") or "").lower()
        if kind not in _KINDS:
            continue

        if kind == "store":
            ext = rs.get("extraction")
            try:
                extraction = ExtractionResult.model_validate(ext) if ext else None
            except Exception:  # noqa: BLE001
                extraction = None
            steps.append(Step(kind="store", extraction=extraction))
        elif kind in ("query", "file"):
            q = rs.get("question")
            steps.append(Step(kind=kind, question=str(q) if q else None))
        elif kind == "action":
            checked = validate_action(str(rs.get("action") or ""), rs.get("args") or {})
            if checked is None:
                steps.append(Step(kind="query", question=rs.get("question")))
            else:
                slug, args = checked
                steps.append(Step(kind="action", action=slug, args=args))
        else:
            steps.append(Step(kind="unknown"))

    if not steps:
        raise BackendParseError("decide: every step was unusable")

    hint = data.get("reply_hint")
    return Plan(steps=steps, reply_hint=str(hint) if hint else None)
