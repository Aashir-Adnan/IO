from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select

from io_assistant.db import models as m
from io_assistant.models_domain import (
    ExtractionResult,
    normalize_domain,
    normalize_kind,
)
from io_assistant.resolve.dates import ground, to_rrule

__all__ = ["PersistError", "PersistResult", "persist_store"]

_STATUS_KINDS = {"task", "chore"}


class PersistError(Exception):
    pass


@dataclass
class PersistResult:
    utterance_id: int
    record_ids: list[int] = field(default_factory=list)
    new_entities: list[tuple[str, str]] = field(default_factory=list)
    gated: bool = False
    gate_reasons: list[str] = field(default_factory=list)


_ENTITY_LISTS = (
    ("person", "people"),
    ("place", "places"),
    ("item", "items"),
)


def persist_store(
    session,
    embedder,
    resolver,
    *,
    utterance_text: str,
    source: str,
    captured_at: datetime,
    extraction: ExtractionResult,
    now: datetime,
    confidence_gate: float,
    confirmed: bool = False,
    existing_utterance_id: int | None = None,
) -> PersistResult:
    # 1. Utterance row — always kept. On a confirm-replay we reuse the
    #    utterance recorded by the gated first pass instead of inserting one.
    if existing_utterance_id is not None:
        utt = session.get(m.Utterance, existing_utterance_id)
        if utt is None:
            raise PersistError(
                f"utterance {existing_utterance_id} no longer exists"
            )
        utterance_id = utt.id
    else:
        utt = m.Utterance(
            text=utterance_text,
            source=source,
            captured_at=captured_at,
            resolved_intent="store",
        )
        session.add(utt)
        session.flush()
        utterance_id = utt.id

    # 2. Resolve pass (read-only). Deduped by (etype, lowered name) so a name
    #    repeated inside one extraction is resolved — and later created — once.
    outcomes: dict[tuple[str, str], object] = {}
    entity_names: dict[tuple[str, str], str] = {}
    entity_aliases: dict[tuple[str, str], list[str]] = {}
    for etype, attr in _ENTITY_LISTS:
        for ent in getattr(extraction, attr):
            key = (etype, ent.name.lower())
            if key in outcomes:
                for alias in ent.aliases:
                    if alias not in entity_aliases[key]:
                        entity_aliases[key].append(alias)
                continue
            entity_names[key] = ent.name
            entity_aliases[key] = list(ent.aliases)
            outcomes[key] = resolver.resolve(etype, ent.name, list(ent.aliases))

    # 3. Gate check.
    gate_reasons: list[str] = []
    for (etype, _lname), outcome in outcomes.items():
        if getattr(outcome, "ambiguous", False):
            name = entity_names[(etype, _lname)]
            gate_reasons.append(
                f"ambiguous {etype} '{name}' — did you mean "
                f"'{outcome.candidate_name}'?"
            )

    for rec in extraction.records:
        if rec.confidence < confidence_gate:
            gate_reasons.append(
                f"low confidence ({rec.confidence}) on '{rec.title}'"
            )
        for phrase in (rec.when_phrase, rec.due_phrase):
            if phrase and not ground(phrase, now).ok:
                gate_reasons.append(f"couldn't ground the date '{phrase}'")
        if rec.recurrence_phrase and to_rrule(rec.recurrence_phrase) is None:
            gate_reasons.append(
                f"couldn't read the repeat rule '{rec.recurrence_phrase}'"
            )

    for occ in extraction.occasions:
        if occ.date_phrase and not ground(occ.date_phrase, now).ok:
            gate_reasons.append(
                f"couldn't ground the date '{occ.date_phrase}'"
            )

    if gate_reasons and not confirmed:
        return PersistResult(
            utterance_id=utterance_id,
            record_ids=[],
            new_entities=[],
            gated=True,
            gate_reasons=gate_reasons,
        )

    # 4. Write pass — inside a SAVEPOINT so a failure rolls back only the
    #    write-pass rows, leaving the already-flushed utterance row intact.
    try:
        with session.begin_nested():
            return _write(
                session,
                embedder,
                resolver,
                extraction,
                now,
                confirmed,
                utterance_id,
                outcomes,
                entity_names,
                entity_aliases,
            )
    except PersistError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise PersistError(str(exc)) from exc


def _write(
    session,
    embedder,
    resolver,
    extraction: ExtractionResult,
    now: datetime,
    confirmed: bool,
    utterance_id: int,
    outcomes: dict,
    entity_names: dict,
    entity_aliases: dict,
) -> PersistResult:
    new_entities: list[tuple[str, str]] = []
    entity_ids: dict[tuple[str, str], int] = {}

    # `outcomes` is already deduped by (etype, lowered name), so each unique
    # entity is created at most once and every later reference reuses the id.
    for key, outcome in outcomes.items():
        etype, _lname = key
        name = entity_names[key]
        if outcome.entity_id is not None:
            entity_ids[key] = outcome.entity_id
        elif getattr(outcome, "ambiguous", False):
            # Confirmed past an ambiguity gate means "yes, that candidate" —
            # accept the suggestion rather than creating the duplicate the
            # gate exists to prevent.
            entity_ids[key] = outcome.candidate_id
        else:
            entity_ids[key] = resolver.create(
                etype, name, list(entity_aliases[key])
            )
            new_entities.append((etype, name))

    def _ensure(etype: str, raw_name: str) -> int | None:
        """Resolve/create an entity referenced only inside a record (not in the
        top-level people/places/items lists), so its link is not dropped."""
        if not raw_name:
            return None
        key = (etype, raw_name.lower())
        if key in entity_ids:
            return entity_ids[key]
        outcome = resolver.resolve(etype, raw_name, [])
        if outcome.entity_id is not None:
            entity_ids[key] = outcome.entity_id
        elif getattr(outcome, "ambiguous", False):
            entity_ids[key] = outcome.candidate_id
        else:
            entity_ids[key] = resolver.create(etype, raw_name, [])
            new_entities.append((etype, raw_name))
        return entity_ids[key]

    # Occasions: dedupe by case-insensitive name.
    occasion_ids: dict[str, int] = {}
    for occ in extraction.occasions:
        existing = session.execute(
            select(m.Occasion).where(
                func.lower(m.Occasion.name) == occ.name.lower()
            )
        ).scalars().first()
        if existing is not None:
            occasion_ids[occ.name.lower()] = existing.id
            continue
        dr = ground(occ.date_phrase, now)
        obj = m.Occasion(
            name=occ.name,
            date=dr.value.date() if dr.value is not None else None,
        )
        obj.embedding = embedder.embed_one(occ.name)
        session.add(obj)
        session.flush()
        occasion_ids[occ.name.lower()] = obj.id

    record_ids: list[int] = []
    for rec in extraction.records:
        kind = normalize_kind(rec.kind)
        status = (
            "open"
            if kind in _STATUS_KINDS and rec.status is None
            else rec.status
        )
        assigned_by_id = None
        if rec.assigned_by:
            assigned_by_id = _ensure("person", rec.assigned_by)

        row = m.Record(
            kind=kind,
            domain=normalize_domain(rec.domain),
            title=rec.title,
            body=rec.body,
            occurred_at=ground(rec.when_phrase, now).value,
            due_at=ground(rec.due_phrase, now).value,
            recurrence_rule=to_rrule(rec.recurrence_phrase),
            status=status,
            assigned_by_person_id=assigned_by_id,
            attributes=rec.attributes,
            source_utterance_id=utterance_id,
        )
        row.embedding = embedder.embed_one(
            (rec.title + "\n" + (rec.body or "")).strip()
        )
        session.add(row)
        session.flush()
        record_ids.append(row.id)

        for pname in rec.people:
            pid = _ensure("person", pname)
            if pid is not None:
                session.add(m.RecordPerson(record_id=row.id, person_id=pid))
        for plname in rec.places:
            plid = _ensure("place", plname)
            if plid is not None:
                session.add(m.RecordPlace(record_id=row.id, place_id=plid))
        for iname in rec.items:
            iid = _ensure("item", iname)
            if iid is not None:
                session.add(m.RecordItem(record_id=row.id, item_id=iid))
        for oname in rec.occasions:
            oid = occasion_ids.get(oname.lower())
            if oid is not None:
                session.add(
                    m.RecordOccasion(record_id=row.id, occasion_id=oid)
                )
        session.flush()

    return PersistResult(
        utterance_id=utterance_id,
        record_ids=record_ids,
        new_entities=new_entities,
        gated=False,
        gate_reasons=[],
    )
