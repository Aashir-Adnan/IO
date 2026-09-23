from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select

from io_assistant.backend.embed import embed_or_none
from io_assistant.query.compile import (
    _TARGET_MODEL,
    compile_count,
    compile_structured,
    recency_column,
)
from io_assistant.query.plan import SubQuery

__all__ = ["Provenance", "RetrievedRow", "retrieve_subquery", "pop_count"]

Provenance = Literal["structured", "semantic", "both"]
_SEMANTIC_LIMIT = 50


@dataclass
class RetrievedRow:
    obj: object
    target_type: str
    provenance: Provenance
    distance: float | None


@dataclass
class _Count:
    """A synthetic single-row carrier for `sq.aggregation == "count"` — never
    a real record. `pipeline.py` strips every `_Count` out (via `pop_count`)
    before `rank()`/`expand_recurrences()` ever see it, since it has no date
    to rank on and no business being merged or recurrence-expanded. `id = -1`
    (a class attribute, shared by every instance) is kept as defense in
    depth — belt-and-suspenders in case a future caller forgets to pop it —
    so `_project`/`_merge` still can't mistake it for a real record."""
    count: int
    id = -1


def pop_count(rows: list[RetrievedRow]) -> tuple[int | None, list[RetrievedRow]]:
    """Split a `retrieve_subquery` result into `(count, remaining rows)`. Call
    this immediately on the raw per-subquery result, before the rows are
    handed to `rank()` — a `_Count` carrier has no date to rank on (it would
    otherwise score like a very old row and could be pushed out of the
    top-N by a large list subquery) and must never reach `_merge`/
    `expand_recurrences`."""
    count = None
    kept: list[RetrievedRow] = []
    for r in rows:
        if isinstance(r.obj, _Count):
            count = r.obj.count
        else:
            kept.append(r)
    return count, kept


def retrieve_subquery(
    session,
    embedder,
    sq: SubQuery,
    entity_ids: dict[str, list[int]],
    now: datetime,
) -> list[RetrievedRow]:
    if sq.aggregation == "count":
        n = session.execute(compile_count(sq, entity_ids, now)).scalar_one()
        return [RetrievedRow(_Count(n), sq.target_type, "structured", None)]

    model = _TARGET_MODEL[sq.target_type]
    structured = session.execute(
        compile_structured(sq, entity_ids, now)
    ).scalars().all()
    rows: dict[int, RetrievedRow] = {
        obj.id: RetrievedRow(obj, sq.target_type, "structured", None)
        for obj in structured
    }

    vec = embed_or_none(embedder, sq.semantic_hint) if sq.semantic_hint else None
    if vec is not None:
        dist = model.embedding.cosine_distance(vec).label("dist")
        stmt = select(model, dist).where(model.embedding.isnot(None))
        if sq.time_window is not None:
            recency = recency_column(sq.target_type)
            if sq.time_window.start is not None:
                stmt = stmt.where(recency >= sq.time_window.start)
            if sq.time_window.end is not None:
                stmt = stmt.where(recency <= sq.time_window.end)
        stmt = stmt.order_by(dist.asc()).limit(_SEMANTIC_LIMIT)
        for obj, d in session.execute(stmt).all():
            d = float(d)
            if obj.id in rows:
                rows[obj.id].provenance = "both"
                rows[obj.id].distance = d
            else:
                rows[obj.id] = RetrievedRow(obj, sq.target_type, "semantic", d)

    return list(rows.values())
