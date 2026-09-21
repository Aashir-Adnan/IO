"""Memory sync engine: push local changes as per-device batch files, pull and
merge other devices' files. Store-agnostic (see store.py). All merge logic is
deterministic Python; the model never decides identity (rules/llm-boundaries).

Files (each device writes only its own, so writes never conflict):
    dev-<id>/batch-<seq>.json.gz      rows/links/tombstones changed since its last push
    dev-<id>/snapshot-<seq>.json.gz   its full state as of <seq>; older batches are deleted
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import time

from sqlalchemy import func, or_, select, text, update

from io_assistant.backend.embed import EmbedError
from io_assistant.config import ResolverConfig
from io_assistant.db import models as m
from io_assistant.resolve.resolver import EntityResolver
from io_assistant.sync.codec import (
    FKS, LINK, LINKS, MODEL, TABLES, IdMap, Unresolved, decode_link, decode_row,
    encode_link, encode_row,
)
from io_assistant.sync.store import SyncStore

CHUNK = 1000            # items per batch file
SNAPSHOT_EVERY = 50     # batches between snapshots (compaction)
FUTURE_SKEW_S = 300     # timestamps further ahead than this are clamped

# entity tables the resolver can match: table -> (resolver type, name column)
ENTITY = {"people": ("person", "canonical_name"), "places": ("place", "name"),
          "items": ("item", "name")}
# link tables referencing an entity: table -> [(link table, entity col, other col)]
REFS = {
    "people": [("record_people", "person_id", "record_id"),
               ("occasion_people", "person_id", "occasion_id")],
    "places": [("record_places", "place_id", "record_id")],
    "items": [("record_items", "item_id", "record_id")],
}


class _NoEmbedder:
    """Sync merges on exact/fuzzy matches only; a vector-only look-alike is not
    confident enough to merge irreversibly."""

    def embed_one(self, text: str):
        raise EmbedError("sync does not use embeddings")


def _dumps(obj) -> bytes:
    return gzip.compress(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def _loads(data: bytes):
    return json.loads(gzip.decompress(data))


class SyncEngine:
    def __init__(self, session_factory, store: SyncStore, device_id: str, *,
                 resolver_cfg: ResolverConfig | None = None, clock=time.time):
        self._sf = session_factory
        self.store = store
        self.device = device_id
        self._cfg = resolver_cfg or ResolverConfig(
            fuzzy_threshold=92, vector_similarity_threshold=0.85,
            confidence_gate_threshold=0.6)
        self._clock = clock
        self.last_error: str | None = None

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

    # -- public -----------------------------------------------------------
    def sync(self) -> tuple[int, int]:
        """push, pull, then push again (a pull can create merge tombstones and
        dirty rows that other devices need). Returns (pushed, pulled)."""
        pushed = self.push()
        pulled = self.pull()
        pushed += self.push()
        with self._sf() as s:
            if self._get(s, "seq", 0) - self._get(s, "snapshot_seq", 0) >= SNAPSHOT_EVERY:
                self.snapshot()
        return pushed, pulled

    # -- push -------------------------------------------------------------
    def _all_items(self, s, ids, *, only_dirty: bool):
        items: list[tuple[dict, tuple]] = []      # (payload, how to mark it clean)
        for table, model, _ in TABLES:
            q = select(model).order_by(model.id)
            if only_dirty:
                q = q.where(or_(model.synced_at.is_(None), model.updated_at > model.synced_at))
            for obj in s.execute(q).scalars():
                items.append(({"k": "row", **encode_row(ids, table, obj)},
                              ("row", model, obj.id, obj.updated_at)))
        for table, model, (a_col, _), (b_col, _) in LINKS:
            q = select(model)
            if only_dirty:
                q = q.where(model.synced_at.is_(None))
            for obj in s.execute(q).scalars():
                items.append(({"k": "link", **encode_link(ids, table, obj)},
                              ("link", model, (a_col, getattr(obj, a_col)),
                               (b_col, getattr(obj, b_col)))))
        q = select(m.SyncTombstone)
        if only_dirty:
            q = q.where(m.SyncTombstone.synced_at.is_(None))
        for t in s.execute(q).scalars():
            items.append(({"k": "tomb", "t": t.table_name, "sync_id": t.sync_id,
                           "merged_into": t.merged_into}, ("tomb", t.id)))
        return items

    def push(self) -> int:
        """Write everything changed since its last push as batch file(s).
        Returns the number of items pushed."""
        with self._sf() as s:
            items = self._all_items(s, IdMap(s), only_dirty=True)
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

    def snapshot(self) -> None:
        """Publish this device's full state and delete its older files. Call
        after push() so nothing dirty is left out."""
        with self._sf() as s:
            seq = self._get(s, "seq", 0)
            if seq == 0:
                return
            items = [p for p, _ in self._all_items(s, IdMap(s), only_dirty=False)]
            self.store.put(f"dev-{self.device}/snapshot-{seq:08d}.json.gz", _dumps(
                {"v": 1, "device": self.device, "seq": seq, "items": items}))
            for path in self.store.list(f"dev-{self.device}/"):
                name = path.rsplit("/", 1)[1]
                kind, n = name.split(".")[0].split("-")
                if int(n) < seq or (kind == "batch" and int(n) <= seq):
                    self.store.delete(path)
            self._set(s, "snapshot_seq", seq)
            s.commit()

    # -- pull -------------------------------------------------------------
    def pull(self) -> int:
        """Apply other devices' new files. Returns the number of items applied.
        A file that references a row not yet seen is retried on the next pull
        (`last_error` says what it is waiting for)."""
        self.last_error = None
        peers: dict[str, dict[str, dict[int, str]]] = {}
        for path in self.store.list("dev-"):
            folder, name = path.split("/", 1)
            dev = folder[4:]
            if dev == self.device:
                continue
            kind, seq = name.split(".")[0].split("-")
            peers.setdefault(dev, {"batch": {}, "snapshot": {}})[kind][int(seq)] = path
        applied = 0
        for dev in sorted(peers):
            try:
                applied += self._pull_device(dev, peers[dev])
            except Unresolved as e:
                self.last_error = f"waiting for {e.table} {e.sync_id}"
        return applied

    def _pull_device(self, dev: str, files: dict) -> int:
        with self._sf() as s:
            last = self._get(s, f"applied:{dev}", 0)
        plan: list[tuple[int, str]] = []
        if files["snapshot"] and max(files["snapshot"]) > last:
            last = max(files["snapshot"])
            plan.append((last, files["snapshot"][last]))
        for seq in sorted(files["batch"]):
            if seq <= last:
                continue
            if seq != last + 1:        # a gap (eventual consistency): wait for it
                break
            plan.append((seq, files["batch"][seq]))
            last = seq
        return sum(self._apply_file(dev, seq, path) for seq, path in plan)

    def _apply_file(self, dev: str, seq: int, path: str) -> int:
        data = _loads(self.store.get(path))
        with self._sf() as s:
            s.info["sync_applying"] = True        # no tombstones for remote changes
            ids = IdMap(s)
            n = 0
            for item in data["items"]:
                n += {"row": self._apply_row, "link": self._apply_link,
                      "tomb": self._apply_tomb}[item["k"]](s, ids, item)
            self._set(s, f"applied:{dev}", seq)
            s.commit()
            return n

    # -- apply helpers ----------------------------------------------------
    def _now(self) -> dt.datetime:
        return dt.datetime.fromtimestamp(self._clock(), tz=dt.timezone.utc)

    @staticmethod
    def _tombstoned(s, table: str, sid: str) -> bool:
        return s.execute(select(m.SyncTombstone.id).where(
            m.SyncTombstone.table_name == table, m.SyncTombstone.sync_id == sid)).first() is not None

    def _decode(self, s, ids, table: str, item: dict):
        """decode_row, tolerating references to rows that were deleted/merged:
        a nullable reference becomes NULL, a required one drops the row."""
        for _ in range(4):
            try:
                return decode_row(ids, table, item)
            except Unresolved as e:
                if not self._tombstoned(s, e.table, e.sync_id):
                    raise
                data, fixed = dict(item["data"]), False
                for col, parent in FKS[table].items():
                    if parent == e.table and data.get(col) == e.sync_id:
                        if not MODEL[table].__table__.c[col].nullable:
                            return None
                        data[col], fixed = None, True
                if not fixed:
                    raise
                item = {**item, "data": data}
        return None

    def _apply_row(self, s, ids, item) -> int:
        table = item["t"]
        model = MODEL[table]
        sid = item["sync_id"]
        alias = s.get(m.SyncAlias, sid)
        if alias is not None:                     # merged away: update the survivor
            sid = alias.canonical
        if self._tombstoned(s, table, sid):
            return 0
        upd = min(dt.datetime.fromisoformat(item["updated_at"]),
                  self._now() + dt.timedelta(seconds=FUTURE_SKEW_S))
        kwargs = self._decode(s, ids, table, item)
        if kwargs is None:
            return 0
        obj = s.execute(select(model).where(model.sync_id == sid)).scalar_one_or_none()

        if obj is None:
            if table in ENTITY and self._collapse(s, ids, table, sid, kwargs, upd):
                return 1
            row = model(**kwargs)
            row.sync_id, row.updated_at, row.synced_at = sid, upd, upd
            s.add(row)
            s.flush()
            ids.remember(table, row.id, sid)
            return 1

        was_done = table == "records" and obj.status == "done"
        old_completed = getattr(obj, "completed_at", None)
        if upd > obj.updated_at:                  # last writer wins
            for k, v in kwargs.items():
                setattr(obj, k, v)
            obj.updated_at, obj.synced_at = upd, upd
            if was_done and obj.status != "done":            # done is sticky
                obj.status, obj.completed_at, obj.synced_at = "done", old_completed, None
            s.flush()
            return 1
        if table == "records" and kwargs.get("status") == "done" and not was_done:
            obj.status, obj.completed_at = "done", kwargs.get("completed_at")
            obj.synced_at = None                                  # publish the completion
            s.flush()
            return 1
        return 0

    def _apply_link(self, s, ids, item) -> int:
        table = item["t"]
        model = LINK[table][0]
        try:
            kw = decode_link(ids, table, item)
        except Unresolved as e:
            if self._tombstoned(s, e.table, e.sync_id):
                return 0
            raise
        cols = list(kw)[:2]
        if s.get(model, (kw[cols[0]], kw[cols[1]])) is not None:
            return 0
        s.add(model(**kw, synced_at=func.now()))
        s.flush()
        return 1

    def _apply_tomb(self, s, ids, item) -> int:
        table, sid, into = item["t"], item["sync_id"], item.get("merged_into")
        model = MODEL[table]
        if self._tombstoned(s, table, sid):
            return 0
        row = s.execute(select(model).where(model.sync_id == sid)).scalar_one_or_none()
        if into:
            if s.get(m.SyncAlias, sid) is None:
                s.add(m.SyncAlias(alias=sid, canonical=into))
            if row is not None:
                winner = s.execute(select(model).where(model.sync_id == into)).scalar_one_or_none()
                if winner is None:                # the survivor's row arrives later
                    row.sync_id = into
                    ids.forget()
                elif winner.id != row.id:
                    self._repoint_and_delete(s, table, row.id, winner.id)
        elif row is not None:
            s.delete(row)
        s.add(m.SyncTombstone(table_name=table, sync_id=sid, merged_into=into,
                              synced_at=func.now()))     # already known everywhere
        s.flush()
        return 1

    # -- duplicate entities -----------------------------------------------
    def _collapse(self, s, ids, table, sid, kwargs, upd) -> bool:
        """An incoming entity that confidently matches an existing one (exact or
        fuzzy, never vector-only) is the same entity: the earlier-created row
        keeps its sync_id, the other is merged into it."""
        etype, name_attr = ENTITY[table]
        out = EntityResolver(s, _NoEmbedder(), self._cfg).resolve(
            etype, kwargs[name_attr], kwargs.get("aliases") or [])
        if out.is_new or out.ambiguous or out.entity_id is None:
            return False
        local = s.get(MODEL[table], out.entity_id)
        old = local.sync_id
        remote_wins = (kwargs["created_at"], sid) < (local.created_at, old)
        names = [local.aliases or [], kwargs.get("aliases") or [], [kwargs[name_attr]]]
        merged = list(local.aliases or [])
        for n in (x for group in names[1:] for x in group):
            if n != getattr(local, name_attr) and n not in merged:
                merged.append(n)
        if merged != list(local.aliases or []):
            local.aliases = merged
        loser, winner = (old, sid) if remote_wins else (sid, old)
        if remote_wins:
            local.sync_id = sid
            ids.forget()
        for a, c in ((loser, winner),):
            if s.get(m.SyncAlias, a) is None:
                s.add(m.SyncAlias(alias=a, canonical=c))
        s.add(m.SyncTombstone(table_name=table, sync_id=loser, merged_into=winner))
        s.flush()
        return True

    @staticmethod
    def _repoint_and_delete(s, table: str, loser_id: int, winner_id: int) -> None:
        for link, col, other in REFS.get(table, []):
            s.execute(text(
                f"UPDATE {link} l SET {col} = :w WHERE {col} = :l AND NOT EXISTS "
                f"(SELECT 1 FROM {link} x WHERE x.{col} = :w AND x.{other} = l.{other})"),
                {"w": winner_id, "l": loser_id})
        if table == "people":
            s.execute(text("UPDATE records SET assigned_by_person_id = :w "
                           "WHERE assigned_by_person_id = :l"), {"w": winner_id, "l": loser_id})
        s.delete(s.get(MODEL[table], loser_id))
