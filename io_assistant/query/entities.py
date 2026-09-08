from __future__ import annotations

from sqlalchemy import func, select

from io_assistant.db import models as m
from io_assistant.resolve.resolver import EntityResolver

__all__ = ["resolve_query_entities"]

_TYPES = ("person", "place", "item")


def resolve_query_entities(
    resolver: EntityResolver, session, names: list[str]
) -> dict[str, list[int]]:
    """Map each unresolved name to matched entity ids, keyed by entity type.
    Read-only: unmatched names contribute nothing."""
    out: dict[str, list[int]] = {
        "person": [], "place": [], "item": [], "occasion": [],
    }
    for name in names:
        for etype in _TYPES:
            eid = resolver.lookup(etype, name)
            if eid is not None and eid not in out[etype]:
                out[etype].append(eid)
        occ = session.execute(
            select(m.Occasion.id).where(
                func.lower(m.Occasion.name) == name.lower()
            )
        ).scalars().first()
        if occ is not None and occ not in out["occasion"]:
            out["occasion"].append(occ)
    return out
