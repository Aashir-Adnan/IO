"""Data for the To-do and Important widgets and the pending-tasks window.
Pure SQL + Python: no model. "Today" is the UTC date, like the rest of IO."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select

from io_assistant.db import models as m
from io_assistant.query.respond import _due_label

TASK_KINDS = ("task", "chore")


def _group(due: dt.datetime | None, now: dt.datetime) -> str:
    if due is None:
        return "none"
    if due.date() < now.date():
        return "overdue"        # by date: a bare task due 00:00 today is not overdue
    return "today" if due.date() == now.date() else "upcoming"


def pending_tasks(session, now: dt.datetime, limit: int = 50) -> list[dict]:
    """Open tasks/chores: overdue, today, upcoming, then undated."""
    rows = session.execute(
        select(m.Record)
        .where(m.Record.kind.in_(TASK_KINDS), m.Record.status == "open")
        .order_by(m.Record.due_at.asc().nulls_last(), m.Record.created_at.asc())
        .limit(limit)
    ).scalars().all()
    out = []
    for r in rows:
        label = _due_label(r.due_at, now)
        out.append({
            "id": r.id, "title": r.title, "kind": r.kind,
            "due_at": r.due_at.isoformat() if r.due_at else None,
            "group": _group(r.due_at, now),
            "due_label": label[:1].upper() + label[1:] if label else None,
        })
    return out


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"


def alerts(session, now: dt.datetime) -> list[dict]:
    """IO's own alerts: overdue tasks, today's tasks, occasions within a week."""
    tasks = pending_tasks(session, now, limit=200)
    out: list[dict] = []
    for group, phrase in (("overdue", "{n} overdue {t}"), ("today", "{n} {t} today")):
        hit = [t for t in tasks if t["group"] == group]
        if hit:
            out.append({"kind": group, "text": phrase.format(n=len(hit), t="task" if len(hit) == 1 else "tasks"),
                        "detail": ", ".join(t["title"] for t in hit[:3])})
    week = now.date() + dt.timedelta(days=7)
    for o in session.execute(
        select(m.Occasion).where(m.Occasion.date >= now.date(), m.Occasion.date <= week)
        .order_by(m.Occasion.date.asc()).limit(5)
    ).scalars():
        days = (o.date - now.date()).days
        when = "today" if days == 0 else f"in {_plural(days, 'day')}"
        out.append({"kind": "occasion", "text": f"{o.name} {when}", "detail": ""})
    return out
