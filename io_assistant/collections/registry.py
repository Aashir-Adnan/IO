"""The learned-collections registry — pure Python, no model, no embedder.

The extraction model only *proposes* an ``ExtractedCollection`` (name / synonyms
/ item_noun / checkable) on the first item of an ad-hoc personal list. This
module owns identity: ``upsert_collection`` dedupes by ``kind_slug`` and unions
synonyms; ``resolve_collection`` maps a free-text phrase back to a stored row so
"what's on my movies-to-watch list" stays findable.
"""
from __future__ import annotations

from datetime import datetime

from rapidfuzz import fuzz
from sqlalchemy import select

from io_assistant.db import models as m
from io_assistant.models_domain import ExtractedCollection, normalize_kind

__all__ = ["upsert_collection", "describe_collections", "resolve_collection",
           "checkable_kinds"]

_MAX_LINES = 20
_FUZZY = 82


def _norm_syn(xs) -> list[str]:
    seen: dict[str, None] = {}
    for x in xs:
        s = str(x).strip().lower()
        if s:
            seen.setdefault(s, None)
    return list(seen)


def upsert_collection(session, *, kind_slug: str, proposal: ExtractedCollection,
                      example_record_id: int | None, now: datetime) -> m.Collection:
    slug = normalize_kind(kind_slug)
    row = session.execute(
        select(m.Collection).where(m.Collection.kind_slug == slug)
    ).scalars().first()
    syns = _norm_syn([*proposal.synonyms, proposal.name, slug])
    if row is None:
        row = m.Collection(
            name=proposal.name.strip() or slug,
            kind_slug=slug,
            item_noun=(proposal.item_noun or None),
            synonyms=syns,
            field_hint={"checkable": bool(proposal.checkable)},
            example_record_id=example_record_id,
            created_at=now, updated_at=now,
        )
        session.add(row)
        session.flush()
        return row
    row.synonyms = _norm_syn([*row.synonyms, *syns])
    if not row.item_noun and proposal.item_noun:
        row.item_noun = proposal.item_noun
    fh = dict(row.field_hint or {})
    fh.setdefault("checkable", bool(proposal.checkable))
    row.field_hint = fh
    if row.example_record_id is None and example_record_id is not None:
        row.example_record_id = example_record_id
    row.updated_at = now
    session.flush()
    return row


def describe_collections(session) -> str:
    rows = session.execute(
        select(m.Collection).order_by(m.Collection.created_at)
    ).scalars().all()[:_MAX_LINES]
    if not rows:
        return ""
    out = []
    for c in rows:
        say = ", ".join(f'"{s}"' for s in c.synonyms[:4]) or f'"{c.name}"'
        noun = f" — {c.item_noun}" if c.item_noun else ""
        out.append(f"- {c.kind_slug}{noun} (say: {say})")
    return "\n".join(out)


def resolve_collection(session, phrase: str):
    p = (phrase or "").strip().lower()
    if not p:
        return None
    rows = session.execute(select(m.Collection)).scalars().all()
    for c in rows:
        if c.kind_slug == normalize_kind(p) or p in {s.lower() for s in c.synonyms}:
            return c
    best, best_c = 0.0, None
    for c in rows:
        for cand in (c.name, *c.synonyms):
            sc = fuzz.WRatio(p, cand)
            if sc > best:
                best, best_c = sc, c
    return best_c if best >= _FUZZY else None


def checkable_kinds(session) -> set[str]:
    return {
        c.kind_slug
        for c in session.execute(select(m.Collection)).scalars().all()
        if (c.field_hint or {}).get("checkable")
    }
