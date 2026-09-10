from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select

from io_assistant.db import models as m
from io_assistant.query.plan import SubQuery

__all__ = ["compile_structured", "recency_column"]

_TARGET_MODEL = {
    "record": m.Record,
    "person": m.Person,
    "place": m.Place,
    "occasion": m.Occasion,
}
_LINK = {
    "person": (m.RecordPerson.person_id, m.RecordPerson.record_id),
    "place": (m.RecordPlace.place_id, m.RecordPlace.record_id),
    "item": (m.RecordItem.item_id, m.RecordItem.record_id),
    "occasion": (m.RecordOccasion.occasion_id, m.RecordOccasion.record_id),
}
_LIMIT = 200


def recency_column(target_type: str):
    if target_type == "record":
        return func.coalesce(
            m.Record.occurred_at, m.Record.due_at, m.Record.created_at
        )
    if target_type == "occasion":
        return func.coalesce(m.Occasion.date, m.Occasion.created_at)
    return _TARGET_MODEL[target_type].created_at


def compile_structured(
    sq: SubQuery, entity_ids: dict[str, list[int]], now: datetime
) -> Select:
    model = _TARGET_MODEL[sq.target_type]
    recency = recency_column(sq.target_type)
    conds = []

    if sq.target_type == "record":
        if sq.kind_filter:
            conds.append(m.Record.kind.in_(sq.kind_filter))
        if sq.domain_filter:
            conds.append(m.Record.domain.in_(sq.domain_filter))
        if sq.status_filter:
            conds.append(m.Record.status.in_(sq.status_filter))
        for etype, (link_eid, link_rid) in _LINK.items():
            ids = entity_ids.get(etype) or []
            if ids:
                conds.append(
                    select(link_rid)
                    .where(and_(link_rid == m.Record.id, link_eid.in_(ids)))
                    .exists()
                )
    else:
        ids = entity_ids.get(sq.target_type) or []
        if ids:
            conds.append(model.id.in_(ids))

    # Read-time roll-forward: when a query explicitly asks for open records, an
    # open task whose due date has passed is always in-window — an overdue task
    # is still "due", so a "what's on my plate" / "anything due today" query must
    # surface it regardless of the time window. done/dropped rows still obey it.
    open_rollforward = (
        sq.target_type == "record"
        and sq.status_filter is not None
        and "open" in sq.status_filter
    )

    if sq.time_window is not None:
        window = []
        if sq.time_window.start is not None:
            window.append(recency >= sq.time_window.start)
        if sq.time_window.end is not None:
            window.append(recency <= sq.time_window.end)
        if window:
            if open_rollforward:
                conds.append(
                    or_(
                        and_(*window),
                        and_(
                            m.Record.status == "open",
                            m.Record.due_at <= now,
                        ),
                    )
                )
            else:
                conds.append(and_(*window))

    stmt = select(model)
    if conds:
        stmt = stmt.where(and_(*conds))
    return stmt.order_by(recency.desc()).limit(_LIMIT)
