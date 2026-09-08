from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from io_assistant.models_domain import (
    AnswerShape,
    normalize_domain,
    normalize_kind,
)
from io_assistant.resolve.dates import ground

__all__ = [
    "TargetType",
    "Aggregation",
    "TimeWindow",
    "SubQuery",
    "QueryPlan",
    "PlanError",
    "ground_plan",
]

TargetType = Literal["record", "person", "place", "occasion"]
Aggregation = Literal["list", "count", "latest"]
_STATUSES = {"open", "done", "dropped"}
_TARGETS = {"record", "person", "place", "occasion"}
_AGGS = {"list", "count", "latest"}
_SHAPES = {"text", "markdown", "diagram"}


class PlanError(Exception):
    pass


class TimeWindow(BaseModel):
    start: datetime | None = None
    end: datetime | None = None


class SubQuery(BaseModel):
    target_type: TargetType = "record"
    kind_filter: list[str] | None = None
    domain_filter: list[str] | None = None
    entities: list[str] = Field(default_factory=list)
    time_window: TimeWindow | None = None
    status_filter: list[str] | None = None
    semantic_hint: str | None = None
    aggregation: Aggregation = "list"


class QueryPlan(BaseModel):
    subqueries: list[SubQuery] = Field(default_factory=list)
    answer_shape: AnswerShape = "text"


def _dedupe(xs: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for x in xs:
        seen.setdefault(x, None)
    return list(seen)


def _ground_bound(value, now: datetime) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    res = ground(str(value), now)
    return res.value if res.ok else None


def _ground_window(raw: dict | None, now: datetime) -> TimeWindow | None:
    if not raw:
        return None
    start = _ground_bound(raw.get("start"), now)
    end = _ground_bound(raw.get("end"), now)
    if start is None and end is None:
        text = " ".join(str(raw.get(k) or "") for k in ("start", "end")).lower()
        if "past" in text or "last" in text or "ago" in text:
            end = now
        else:
            return None
    return TimeWindow(start=start, end=end)


def _clean_subquery(raw: dict, now: datetime) -> SubQuery:
    tt = raw.get("target_type")
    kinds = [normalize_kind(k) for k in (raw.get("kind_filter") or [])]
    # For a *filter*, an unrecognized domain must be dropped, not coerced to
    # "other" (that would silently broaden the query to every other-domain row).
    domains = []
    for x in raw.get("domain_filter") or []:
        d = normalize_domain(x)
        if d and (d != "other" or str(x).strip().lower() == "other"):
            domains.append(d)
    statuses = [s for s in (raw.get("status_filter") or []) if s in _STATUSES]
    agg = raw.get("aggregation")
    return SubQuery(
        target_type=tt if tt in _TARGETS else "record",
        kind_filter=_dedupe(kinds) or None,
        domain_filter=_dedupe(domains) or None,
        entities=[str(e) for e in (raw.get("entities") or []) if str(e).strip()],
        time_window=_ground_window(raw.get("time_window"), now),
        status_filter=_dedupe(statuses) or None,
        semantic_hint=(raw.get("semantic_hint") or None),
        aggregation=agg if agg in _AGGS else "list",
    )


def ground_plan(raw: object, now: datetime) -> QueryPlan:
    if not isinstance(raw, dict):
        raise PlanError(f"plan must be a JSON object, got {type(raw).__name__}")
    subs_raw = raw.get("subqueries") or []
    subs = [_clean_subquery(s, now) for s in subs_raw if isinstance(s, dict)]
    if not subs:
        subs = [SubQuery()]
    shape = raw.get("answer_shape")
    return QueryPlan(
        subqueries=subs,
        answer_shape=shape if shape in _SHAPES else "text",
    )
