from __future__ import annotations

from sqlalchemy import select

from io_assistant.db import models as m
from io_assistant.models_domain import (
    Card,
    CollectionCard,
    EntityRef,
    RecordCard,
    SourcesCard,
    TaskListCard,
    TaskListItem,
)

__all__ = ["store_cards", "query_cards"]

_ETYPES = (
    ("person", m.RecordPerson, m.RecordPerson.person_id, m.Person, m.Person.canonical_name),
    ("place", m.RecordPlace, m.RecordPlace.place_id, m.Place, m.Place.name),
    ("item", m.RecordItem, m.RecordItem.item_id, m.Item, m.Item.name),
    ("occasion", m.RecordOccasion, m.RecordOccasion.occasion_id, m.Occasion, m.Occasion.name),
)


def _entities_for(session, record_id: int) -> list[EntityRef]:
    out: list[EntityRef] = []
    for etype, link, link_eid, model, name_col in _ETYPES:
        rows = session.execute(
            select(model.id, name_col)
            .join(link, link_eid == model.id)
            .where(link.record_id == record_id)
        ).all()
        out += [EntityRef(etype=etype, id=i, name=n) for i, n in rows]
    return out


def store_cards(session, persist_result) -> list[Card]:
    cards: list[Card] = []
    for rid in getattr(persist_result, "record_ids", []):
        rec = session.get(m.Record, rid)
        if rec is None:
            continue
        cards.append(RecordCard(
            record_id=rec.id, kind=rec.kind, domain=rec.domain, title=rec.title,
            entities=_entities_for(session, rec.id),
            when=rec.occurred_at, due=rec.due_at, status=rec.status,
        ))
    return cards


def query_cards(session, answer) -> list[Card]:
    cards: list[Card] = []
    if answer.source_record_ids:
        cards.append(SourcesCard(
            record_ids=list(answer.source_record_ids),
            count=len(answer.source_record_ids),
            labels=["memory"],
        ))
    lr = getattr(answer, "list_records", [])
    slugs = {r.kind for r in lr}
    if lr and len(slugs) == 1:
        c = session.execute(
            select(m.Collection).where(m.Collection.kind_slug == next(iter(slugs)))
        ).scalars().first()
        if c is not None:
            cards.append(CollectionCard(
                name=c.name, item_noun=c.item_noun, kind_slug=c.kind_slug,
                checkable=bool((c.field_hint or {}).get("checkable")),
                items=[TaskListItem(record_id=r.record_id, title=r.title,
                                    status=r.status, due=r.due) for r in lr],
            ))
            return cards   # collection card replaces the tasklist card
    statusful = [
        r for r in lr
        if r.status in ("open", "done", "dropped") or r.due is not None
    ]
    if statusful and len(statusful) >= max(1, len(lr) // 2):
        cards.append(TaskListCard(items=[
            TaskListItem(record_id=r.record_id, title=r.title, status=r.status, due=r.due)
            for r in statusful
        ]))
    return cards
