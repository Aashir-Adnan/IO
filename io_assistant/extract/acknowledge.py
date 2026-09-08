from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from io_assistant.db import models as m

__all__ = ["build_fact_list"]

_LINKS = (
    ("with", m.RecordPerson, m.RecordPerson.person_id, m.Person.id, m.Person.canonical_name),
    ("at", m.RecordPlace, m.RecordPlace.place_id, m.Place.id, m.Place.name),
    ("item", m.RecordItem, m.RecordItem.item_id, m.Item.id, m.Item.name),
    ("occasion", m.RecordOccasion, m.RecordOccasion.occasion_id, m.Occasion.id, m.Occasion.name),
)


def build_fact_list(session, persist_result, extraction, now: datetime) -> str:
    """A plain-text summary of exactly what persist_store wrote — the only input
    the `acknowledge` prompt is given. No model call."""
    lines: list[str] = []
    for rid in getattr(persist_result, "record_ids", []):
        rec = session.get(m.Record, rid)
        if rec is None:
            continue
        parts = [f'{rec.kind} "{rec.title}"']
        for word, link, link_eid, ent_id, ent_name in _LINKS:
            names = [
                n
                for (n,) in session.execute(
                    select(ent_name)
                    .join(link, link_eid == ent_id)
                    .where(link.record_id == rid)
                ).all()
            ]
            if names:
                parts.append(f"{word} {', '.join(names)}")
        when = rec.occurred_at or rec.due_at
        if when is not None:
            parts.append(f"when {when.date().isoformat()}")
        if rec.status:
            parts.append(f"status {rec.status}")
        lines.append("; ".join(parts))
    return "\n".join(lines) or "nothing recorded"
