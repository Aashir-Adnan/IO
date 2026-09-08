from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from datetime import datetime, timedelta

from dateutil.rrule import rrulestr

from io_assistant.query.rank import RankedRow

__all__ = ["RecurrenceInstance", "expand_recurrences", "anchor_for"]

_MAX_INSTANCES = 50


@dataclass
class RecurrenceInstance:
    obj: object
    target_type: str
    score: float
    occurs_at: datetime


def anchor_for(obj, now: datetime) -> datetime:
    for attr in ("occurred_at", "due_at", "date", "created_at"):
        v = getattr(obj, attr, None)
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=now.tzinfo)
        if isinstance(v, _dt.date):
            return datetime(v.year, v.month, v.day, tzinfo=now.tzinfo)
    return now


def expand_recurrences(
    rows: list[RankedRow],
    window_start: datetime | None,
    window_end: datetime | None,
    *,
    now: datetime,
) -> list:
    lo = window_start or (now - timedelta(days=30))
    hi = window_end or (now + timedelta(days=30))
    out: list = []
    for row in rows:
        rule = getattr(row.obj, "recurrence_rule", None)
        if not rule:
            out.append(row)
            continue
        try:
            rs = rrulestr("RRULE:" + rule, dtstart=anchor_for(row.obj, now))
            fires = list(rs.between(lo, hi, inc=True))[:_MAX_INSTANCES]
        except (ValueError, TypeError):
            out.append(row)
            continue
        if not fires:
            out.append(row)
            continue
        for when in fires:
            out.append(
                RecurrenceInstance(row.obj, row.target_type, row.score, when)
            )
    return out
