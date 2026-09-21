"""Row <-> wire-dict codec for memory sync.

Local integer ids never leave the device: every foreign key is carried as the
target row's global `sync_id`, and affiliations (link tables) are identified by
the pair of parent sync_ids. Embeddings are never synced (each device
re-embeds; see backend/backfill.py)."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, DateTime, select

from io_assistant.db import models as m

# (table, model, {fk column -> parent table}) — parents before children.
TABLES: list[tuple[str, type, dict[str, str]]] = [
    ("utterances", m.Utterance, {}),
    ("people", m.Person, {}),
    ("places", m.Place, {}),
    ("items", m.Item, {}),
    ("occasions", m.Occasion, {}),
    ("conversations", m.Conversation, {}),
    ("records", m.Record, {"assigned_by_person_id": "people",
                           "source_utterance_id": "utterances"}),
    ("collections", m.Collection, {"example_record_id": "records"}),
    ("messages", m.Message, {"conversation_id": "conversations",
                             "utterance_id": "utterances"}),
]
# (table, model, (fk column a, parent a), (fk column b, parent b))
LINKS: list[tuple[str, type, tuple[str, str], tuple[str, str]]] = [
    ("record_people", m.RecordPerson, ("record_id", "records"), ("person_id", "people")),
    ("record_places", m.RecordPlace, ("record_id", "records"), ("place_id", "places")),
    ("record_items", m.RecordItem, ("record_id", "records"), ("item_id", "items")),
    ("record_occasions", m.RecordOccasion, ("record_id", "records"), ("occasion_id", "occasions")),
    ("occasion_people", m.OccasionPerson, ("occasion_id", "occasions"), ("person_id", "people")),
]

MODEL = {t: model for t, model, _ in TABLES}
FKS = {t: fks for t, _, fks in TABLES}
LINK = {t: (model, a, b) for t, model, a, b in LINKS}

_SKIP = {"id", "embedding", "sync_id", "synced_at", "updated_at"}


class Unresolved(Exception):
    """A referenced parent isn't (yet) in the local database."""

    def __init__(self, table: str, sync_id: str):
        super().__init__(f"{table} {sync_id} not found")
        self.table, self.sync_id = table, sync_id


class IdMap:
    """local id <-> sync_id lookups for one session, with a small cache.
    `local_of` follows sync_aliases, so a merged-away id resolves to the
    survivor."""

    def __init__(self, session):
        self.s = session
        self._to_sync: dict[tuple[str, int], str] = {}
        self._to_local: dict[tuple[str, str], int] = {}

    def sync_of(self, table: str, local_id: int) -> str:
        key = (table, local_id)
        if key not in self._to_sync:
            model = MODEL[table]
            sid = self.s.execute(
                select(model.sync_id).where(model.id == local_id)).scalar_one()
            self._to_sync[key] = sid
        return self._to_sync[key]

    def local_of(self, table: str, sync_id: str) -> int:
        key = (table, sync_id)
        if key not in self._to_local:
            alias = self.s.get(m.SyncAlias, sync_id)
            target = alias.canonical if alias is not None else sync_id
            model = MODEL[table]
            lid = self.s.execute(
                select(model.id).where(model.sync_id == target)).scalar_one_or_none()
            if lid is None:
                raise Unresolved(table, sync_id)
            self._to_local[key] = lid
        return self._to_local[key]

    def remember(self, table: str, local_id: int, sync_id: str) -> None:
        self._to_sync[(table, local_id)] = sync_id
        self._to_local[(table, sync_id)] = local_id

    def forget(self) -> None:
        self._to_sync.clear()
        self._to_local.clear()


def _cols(model):
    return [c for c in model.__table__.columns
            if c.name not in _SKIP and c.computed is None]


def _iso(v):
    return v.isoformat() if isinstance(v, (dt.datetime, dt.date)) else v


def _parse(col, v):
    if v is None:
        return None
    if isinstance(col.type, DateTime):
        return dt.datetime.fromisoformat(v)
    if isinstance(col.type, Date):
        return dt.date.fromisoformat(v)
    return v


def encode_row(ids: IdMap, table: str, obj) -> dict:
    fks = FKS[table]
    data = {}
    for c in _cols(MODEL[table]):
        v = getattr(obj, c.name)
        if c.name in fks and v is not None:
            v = ids.sync_of(fks[c.name], v)
        data[c.name] = _iso(v)
    return {"t": table, "sync_id": obj.sync_id,
            "updated_at": obj.updated_at.isoformat(), "data": data}


def decode_row(ids: IdMap, table: str, payload: dict) -> dict:
    fks = FKS[table]
    out = {}
    for c in _cols(MODEL[table]):
        if c.name not in payload["data"]:
            continue
        v = payload["data"][c.name]
        if c.name in fks and v is not None:
            v = ids.local_of(fks[c.name], v)
        else:
            v = _parse(c, v)
        out[c.name] = v
    return out


def link_key(a_sync: str, b_sync: str) -> str:
    return f"{a_sync}:{b_sync}"


def encode_link(ids: IdMap, table: str, obj) -> dict:
    _, (a_col, a_tbl), (b_col, b_tbl) = LINK[table]
    return {"t": table, "a": ids.sync_of(a_tbl, getattr(obj, a_col)),
            "b": ids.sync_of(b_tbl, getattr(obj, b_col)), "role": obj.role}


def decode_link(ids: IdMap, table: str, payload: dict) -> dict:
    _, (a_col, a_tbl), (b_col, b_tbl) = LINK[table]
    return {a_col: ids.local_of(a_tbl, payload["a"]),
            b_col: ids.local_of(b_tbl, payload["b"]),
            "role": payload.get("role")}
