from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select

from io_assistant.query.compile import (
    _TARGET_MODEL,
    compile_structured,
    recency_column,
)
from io_assistant.query.plan import SubQuery

__all__ = ["Provenance", "RetrievedRow", "retrieve_subquery"]

Provenance = Literal["structured", "semantic", "both"]
_SEMANTIC_LIMIT = 50


@dataclass
class RetrievedRow:
    obj: object
    target_type: str
    provenance: Provenance
    distance: float | None


def retrieve_subquery(
    session,
    embedder,
    sq: SubQuery,
    entity_ids: dict[str, list[int]],
    now: datetime,
) -> list[RetrievedRow]:
    model = _TARGET_MODEL[sq.target_type]
    structured = session.execute(
        compile_structured(sq, entity_ids, now)
    ).scalars().all()
    rows: dict[int, RetrievedRow] = {
        obj.id: RetrievedRow(obj, sq.target_type, "structured", None)
        for obj in structured
    }

    if sq.semantic_hint:
        vec = embedder.embed_one(sq.semantic_hint)
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
