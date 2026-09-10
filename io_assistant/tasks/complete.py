from __future__ import annotations

from datetime import datetime

from io_assistant.db import models as m

__all__ = ["set_record_status"]


def set_record_status(session, record: m.Record, status: str, now: datetime) -> None:
    """The one place a record's task status changes. `done` stamps
    completed_at (once); `open` clears it. Caller owns the commit."""
    record.status = status
    if status == "done" and record.completed_at is None:
        record.completed_at = now
    elif status == "open":
        record.completed_at = None
