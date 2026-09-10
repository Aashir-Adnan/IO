from __future__ import annotations

import datetime as _dt

from io_assistant.backend.interface import Backend

__all__ = ["Responder", "rows_to_json"]

_EMPTY = "I don't have anything on that yet."


def _iso(v):
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.isoformat()
    return None


def _name_of(obj) -> str | None:
    """The human label for a row. `Person` uses `canonical_name`; every other
    entity (`Place`/`Item`/`Occasion`) uses `name`; `Record` uses `title`."""
    return (
        getattr(obj, "title", None)
        or getattr(obj, "name", None)
        or getattr(obj, "canonical_name", None)
    )


def _clip(s, n: int = 600) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


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
            "title": _name_of(obj),
            "when": when,
        }
        # The substance often lives outside the title: a Record's `body`, an
        # entity's `notes`, structured `attributes`. Without these the phrasing
        # model sees only a headline (e.g. a "Family relationships" record whose
        # names are all in `body`) and refuses to answer.
        body = getattr(obj, "body", None)
        if body:
            d["detail"] = _clip(body)
        notes = getattr(obj, "notes", None)
        if notes:
            d["notes"] = _clip(notes)
        for attr in ("kind", "domain", "status"):
            v = getattr(obj, attr, None)
            if v is not None:
                d[attr] = v
        attributes = getattr(obj, "attributes", None)
        if isinstance(attributes, dict) and attributes:
            d["attributes"] = attributes
        out.append(d)
    return out


class Responder:
    def __init__(self, backend: Backend):
        self._backend = backend

    def run(
        self, question: str, rows: list, shape: str, *, context: str | None = None
    ) -> str:
        if not rows:
            return _EMPTY
        return self._backend.phrase(
            question, rows_to_json(rows), shape, context=context
        )
