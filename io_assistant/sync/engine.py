"""Memory sync engine: push local changes as per-device batch files, pull and
merge other devices' files. Store-agnostic (see store.py). All merge logic is
deterministic Python; the model never decides identity (rules/llm-boundaries)."""
from __future__ import annotations

import gzip
import json
import time

from sqlalchemy import func, or_, select, update

from io_assistant.db import models as m
from io_assistant.sync.codec import LINKS, TABLES, IdMap, encode_link, encode_row
from io_assistant.sync.store import SyncStore

CHUNK = 1000            # items per batch file
SNAPSHOT_EVERY = 50     # batches between snapshots (compaction)


def _dumps(obj) -> bytes:
    return gzip.compress(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def _loads(data: bytes):
    return json.loads(gzip.decompress(data))


class SyncEngine:
    def __init__(self, session_factory, store: SyncStore, device_id: str, *,
                 resolver_cfg=None, clock=time.time):
        self._sf = session_factory
        self.store = store
        self.device = device_id
        self._resolver_cfg = resolver_cfg
        self._clock = clock

    # -- state ------------------------------------------------------------
    def _get(self, s, key: str, default):
        row = s.get(m.SyncState, key)
        return default if row is None else row.value["v"]

    def _set(self, s, key: str, value) -> None:
        row = s.get(m.SyncState, key)
        if row is None:
            s.add(m.SyncState(key=key, value={"v": value}))
        else:
            row.value = {"v": value}

    # -- push -------------------------------------------------------------
    def push(self) -> int:
        """Write everything changed since its last push as batch file(s).
        Returns the number of items pushed."""
        with self._sf() as s:
            ids = IdMap(s)
            items: list[tuple[dict, tuple]] = []      # (payload, how to mark it clean)
            for table, model, _ in TABLES:
                dirty = s.execute(select(model).where(or_(
                    model.synced_at.is_(None), model.updated_at > model.synced_at,
                )).order_by(model.id)).scalars().all()
                for obj in dirty:
                    items.append(({"k": "row", **encode_row(ids, table, obj)},
                                  ("row", model, obj.id, obj.updated_at)))
            for table, model, (a_col, _), (b_col, _) in LINKS:
                for obj in s.execute(select(model).where(model.synced_at.is_(None))).scalars():
                    items.append(({"k": "link", **encode_link(ids, table, obj)},
                                  ("link", model, (a_col, getattr(obj, a_col)),
                                   (b_col, getattr(obj, b_col)))))
            for t in s.execute(select(m.SyncTombstone).where(
                    m.SyncTombstone.synced_at.is_(None))).scalars():
                items.append(({"k": "tomb", "t": t.table_name, "sync_id": t.sync_id,
                               "merged_into": t.merged_into}, ("tomb", t.id)))
            if not items:
                return 0

            seq = self._get(s, "seq", 0)
            for i in range(0, len(items), CHUNK):
                chunk = items[i:i + CHUNK]
                seq += 1
                self.store.put(f"dev-{self.device}/batch-{seq:08d}.json.gz", _dumps(
                    {"v": 1, "device": self.device, "seq": seq,
                     "items": [p for p, _ in chunk]}))
                self._mark_clean(s, [mk for _, mk in chunk])
                self._set(s, "seq", seq)
                s.commit()
            return len(items)

    @staticmethod
    def _mark_clean(s, marks) -> None:
        for mk in marks:
            if mk[0] == "row":
                _, model, rid, upd = mk
                # only if unchanged since it was read; updated_at is re-assigned
                # to itself so the onupdate default doesn't bump it
                s.execute(update(model).where(model.id == rid, model.updated_at == upd)
                          .values(synced_at=upd, updated_at=model.updated_at))
            elif mk[0] == "link":
                _, model, (ac, av), (bc, bv) = mk
                s.execute(update(model).where(getattr(model, ac) == av,
                                              getattr(model, bc) == bv)
                          .values(synced_at=func.now()))
            else:
                s.execute(update(m.SyncTombstone).where(m.SyncTombstone.id == mk[1])
                          .values(synced_at=func.now()))
