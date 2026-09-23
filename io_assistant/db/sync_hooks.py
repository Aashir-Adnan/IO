"""Record deletes of synced rows as tombstones, in one place.

A `before_flush` hook on every Session writes a SyncTombstone for each deleted
synced-model row, so no delete path has to remember to. It is suppressed while
the sync engine applies remote changes (`session.info["sync_applying"]`).
DB-level cascades (link tables) need no tombstone: the receiver's own DELETE
cascades the same way."""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session


def install(synced_classes: tuple, tombstone_cls) -> None:
    synced = set(synced_classes)

    @event.listens_for(Session, "before_flush")
    def _record_tombstones(session, flush_context, instances):
        if session.info.get("sync_applying"):
            return
        for obj in list(session.deleted):
            if type(obj) in synced:
                session.add(tombstone_cls(table_name=obj.__tablename__,
                                          sync_id=obj.sync_id))
