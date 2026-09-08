from __future__ import annotations

import datetime as _dt

from io_assistant.backend.interface import Backend

__all__ = ["Responder", "rows_to_json"]

_EMPTY = "I don't have anything on that yet."


def _iso(v):
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    return None


def rows_to_json(rows: list) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        obj = r.obj
        occurs = getattr(r, "occurs_at", None)
        if occurs is not None:
            when = _iso(occurs)
        else:
            when = _iso(
                getattr(obj, "occurred_at", None)
                or getattr(obj, "due_at", None)
                or getattr(obj, "date", None)
                or getattr(obj, "created_at", None)
            )
        d = {
            "type": getattr(r, "target_type", "record"),
            "title": getattr(obj, "title", None) or getattr(obj, "name", None),
            "when": when,
        }
        for attr in ("kind", "domain", "status"):
            v = getattr(obj, attr, None)
            if v is not None:
                d[attr] = v
        out.append(d)
    return out


class Responder:
    def __init__(self, backend: Backend):
        self._backend = backend

    def run(self, question: str, rows: list, shape: str) -> str:
        if not rows:
            return _EMPTY
        return self._backend.phrase(question, rows_to_json(rows), shape)
