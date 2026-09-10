from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from rapidfuzz import fuzz
from sqlalchemy import select

from io_assistant.db import models as m

__all__ = ["set_record_status", "close_record", "CloseOutcome"]

_MATCH_FLOOR = 72.0
_AMBIG_FLOOR = 55.0
_CLEAR_MARGIN = 12.0


def set_record_status(session, record: m.Record, status: str, now: datetime) -> None:
    """The one place a record's task status changes. `done` stamps
    completed_at (once); `open` clears it. Caller owns the commit."""
    record.status = status
    if status == "done" and record.completed_at is None:
        record.completed_at = now
    elif status == "open":
        record.completed_at = None


@dataclass
class CloseOutcome:
    status: Literal["matched", "ambiguous", "none"]
    record: m.Record | None = None
    candidates: list = field(default_factory=list)


def close_record(
    session,
    phrase: str,
    now: datetime,
    *,
    checkable_kinds: set[str],
    target_status: str = "done",
) -> CloseOutcome:
    """Deterministic lexical match of a free-text phrase against open
    status-kind records. No model, no embedder — pure rapidfuzz + one SELECT.
    Never mutates. `target_status` is threaded for a later `dropped` path and
    does not affect scoring."""
    if not phrase.strip() or not checkable_kinds:
        return CloseOutcome("none")
    rows = session.execute(
        select(m.Record).where(
            m.Record.status == "open",
            m.Record.kind.in_(sorted(checkable_kinds)),
        )
    ).scalars().all()
    if not rows:
        return CloseOutcome("none")
    scored = sorted(
        ((fuzz.WRatio(phrase, r.title), r) for r in rows),
        key=lambda t: t[0],
        reverse=True,
    )
    best_score, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= _MATCH_FLOOR and best_score - second >= _CLEAR_MARGIN:
        return CloseOutcome("matched", record=best)
    if best_score >= _AMBIG_FLOOR:
        return CloseOutcome(
            "ambiguous",
            candidates=[r for s, r in scored if s >= _AMBIG_FLOOR][:3],
        )
    return CloseOutcome("none")
