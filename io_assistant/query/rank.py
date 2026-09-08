from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field
from datetime import datetime

from io_assistant.query.retrieve import RetrievedRow

__all__ = ["RankedRow", "rank"]

_STRONGER = {"structured": 1, "semantic": 1, "both": 2}


@dataclass
class RankedRow:
    obj: object
    target_type: str
    provenance: str
    score: float
    components: dict[str, float] = field(default_factory=dict)


def _recency_value(obj):
    for attr in ("occurred_at", "due_at", "date", "created_at"):
        v = getattr(obj, attr, None)
        if v is not None:
            return v
    return None


def _as_dt(v, now: datetime) -> datetime:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=now.tzinfo)
    if isinstance(v, _dt.date):
        return datetime(v.year, v.month, v.day, tzinfo=now.tzinfo)
    return now


def _merge(groups: list[list[RetrievedRow]]) -> list[RetrievedRow]:
    best: dict[tuple[str, int], RetrievedRow] = {}
    for group in groups:
        for r in group:
            key = (r.target_type, r.obj.id)
            cur = best.get(key)
            if cur is None:
                best[key] = RetrievedRow(
                    r.obj, r.target_type, r.provenance, r.distance
                )
                continue
            if r.provenance != cur.provenance and {r.provenance, cur.provenance} <= {
                "structured",
                "semantic",
            }:
                cur.provenance = "both"
            elif _STRONGER[r.provenance] > _STRONGER[cur.provenance]:
                cur.provenance = r.provenance
            if r.distance is not None and (
                cur.distance is None or r.distance < cur.distance
            ):
                cur.distance = r.distance
    return list(best.values())


def rank(
    groups: list[list[RetrievedRow]], now: datetime, *, top_n: int = 20
) -> list[RankedRow]:
    out: list[RankedRow] = []
    for r in _merge(groups):
        rv = _recency_value(r.obj)
        if rv is not None:
            age_days = max(0.0, (now - _as_dt(rv, now)).total_seconds() / 86400.0)
        else:
            age_days = 365.0
        recency = math.exp(-age_days / 30.0)
        similarity = (1.0 - r.distance) if r.distance is not None else 0.0
        structured_rel = 1.0 if r.provenance != "semantic" else 0.4
        prov_bonus = 0.15 if r.provenance == "both" else 0.0
        score = (
            0.30 * recency
            + 0.30 * similarity
            + 0.30 * structured_rel
            + prov_bonus
        )
        out.append(
            RankedRow(
                r.obj,
                r.target_type,
                r.provenance,
                score,
                {
                    "recency": recency,
                    "similarity": similarity,
                    "structured": structured_rel,
                    "provenance": prov_bonus,
                },
            )
        )
    out.sort(key=lambda x: x.score, reverse=True)
    return out[:top_n]
