from __future__ import annotations

import datetime as dt
import os

from sqlalchemy import func, select

from io_assistant.db import models as m

__all__ = ["entity_panel", "standby_panel"]

_ETYPE = {
    "person": (m.Person, m.Person.canonical_name, m.RecordPerson, m.RecordPerson.person_id, "PERSON"),
    "place": (m.Place, m.Place.name, m.RecordPlace, m.RecordPlace.place_id, None),
    "item": (m.Item, m.Item.name, m.RecordItem, m.RecordItem.item_id, None),
    "occasion": (m.Occasion, m.Occasion.name, m.RecordOccasion, m.RecordOccasion.occasion_id, "OCCASION"),
}


def _fact_label(rec) -> str:
    bits = [rec.kind.upper()]
    if rec.domain:
        bits.append(rec.domain.upper())
    return " · ".join(bits)


def entity_panel(session, etype: str, entity_id: int) -> dict | None:
    spec = _ETYPE.get(etype)
    if spec is None:
        return None
    model, name_col, link, link_eid, fixed_role = spec
    ent = session.get(model, entity_id)
    if ent is None:
        return None

    recs = session.execute(
        select(m.Record)
        .join(link, link.record_id == m.Record.id)
        .where(link_eid == entity_id)
        .order_by(func.coalesce(m.Record.occurred_at, m.Record.created_at).desc())
        .limit(6)
    ).scalars().all()

    total = session.execute(
        select(func.count()).select_from(link).where(link_eid == entity_id)
    ).scalar_one()

    role = fixed_role or getattr(ent, "type", None) or getattr(ent, "category", None) or "NOTE"
    facts = [
        {
            "label": _fact_label(r),
            "text": (r.title + (f" — {r.body}" if r.body else "")),
            "record_ids": [r.id],
        }
        for r in recs
    ]

    # confidence = mean cosine similarity of the fact records to the entity embedding
    confidence = 0.0
    if ent.embedding is not None:
        sims = []
        for r in recs:
            if r.embedding is not None:
                d = session.execute(
                    select(model.embedding.cosine_distance(r.embedding))
                    .where(model.id == entity_id)
                ).scalar_one()
                sims.append(max(0.0, 1.0 - float(d)))
        if sims:
            confidence = sum(sims) / len(sims)

    return {
        "etype": etype,
        "id": entity_id,
        "name": getattr(ent, "canonical_name", None) or getattr(ent, "name"),
        "subtitle": f"{str(role).upper()} · {total} NOTES",
        "facts": facts,
        "confidence": round(confidence, 3),
        "sourced_from": len({rid for f in facts for rid in f["record_ids"]}),
    }


def standby_panel(session, config, recall_ms: int) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    name = (
        config.ui.name
        or os.environ.get("USERNAME")
        or os.environ.get("USER")
        or "there"
    )
    memories = session.execute(select(func.count()).select_from(m.Record)).scalar_one()

    chips: list[dict] = []
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + dt.timedelta(days=1)
    n_today = session.execute(
        select(func.count())
        .select_from(m.Record)
        .where(m.Record.kind.in_(("task", "chore")))
        .where(m.Record.status == "open")
        .where(m.Record.due_at >= day_start, m.Record.due_at < day_end)
    ).scalar_one()
    if n_today:
        chips.append({"icon": "list-checks", "text": f"{n_today} task{'s' if n_today != 1 else ''} today", "record_id": None})

    occ = session.execute(
        select(m.Occasion)
        .where(m.Occasion.date >= now.date())
        .order_by(m.Occasion.date.asc())
        .limit(1)
    ).scalar_one_or_none()
    if occ is not None:
        days = (occ.date - now.date()).days
        chips.append({"icon": "users-three",
                      "text": f"{occ.name} in {days} day{'s' if days != 1 else ''}",
                      "record_id": None})

    nxt = session.execute(
        select(m.Record)
        .where(m.Record.due_at >= now)
        .order_by(m.Record.due_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    if nxt is not None:
        wd = nxt.due_at.strftime("%a")
        chips.append({"icon": "circle",
                      "text": f"{nxt.title}, {wd} {nxt.due_at.strftime('%H:%M')}",
                      "record_id": nxt.id})

    return {
        "greeting_name": name,
        "stats": {"memories": memories, "recall_ms": recall_ms, "clock": now.isoformat()},
        "chips": chips,
    }
