from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select

from io_assistant.config import FilesConfig
from io_assistant.db import models as m
from io_assistant.files.paths import AccessGate
from io_assistant.files.walk import classify_media, walk_dir
from io_assistant.models_domain import EntityRef, GalleryCard, GalleryItem

__all__ = ["open_folder", "gallery_from_nodes", "media_item"]

_ENTITY_NAME = {
    "person": m.Person.canonical_name, "place": m.Place.name,
    "item": m.Item.name, "occasion": m.Occasion.name,
}
_ENTITY_MODEL = {
    "person": m.Person, "place": m.Place, "item": m.Item, "occasion": m.Occasion,
}


def _entities_for(session, file_id: int) -> list[EntityRef]:
    return _entities_for_many(session, [file_id]).get(file_id, [])


def _entities_for_many(session, file_ids: list[int]) -> dict[int, list[EntityRef]]:
    """One query per entity type over ALL file ids — so listing a folder of
    200 photos is 4 queries, not 800."""
    out: dict[int, list[EntityRef]] = {}
    if not file_ids:
        return out
    for etype, model in _ENTITY_MODEL.items():
        for fid, eid, name in session.execute(
            select(m.FileEntityLink.file_id, model.id, _ENTITY_NAME[etype])
            .join(model, m.FileEntityLink.entity_id == model.id)
            .where(m.FileEntityLink.file_id.in_(file_ids),
                   m.FileEntityLink.etype == etype)
        ).all():
            out.setdefault(fid, []).append(EntityRef(etype=etype, id=eid, name=name))
    return out


def media_item(session, n) -> GalleryItem:
    """A GalleryItem for an already-indexed media FileNode."""
    qp = quote(n.path)
    return GalleryItem(
        path=n.path,
        media_kind=n.media_kind or "image",
        thumb_url=(f"/files/thumb?path={qp}" if n.thumb_path else None),
        raw_url=f"/files/raw?path={qp}",
        has_thumb=n.thumb_path is not None,
        caption=n.caption,
        entities=_entities_for(session, n.id),
        captured_at=n.captured_at,
        size_bytes=n.size_bytes,
        indexed=True,
    )


def gallery_from_nodes(session, nodes, *, label: str) -> GalleryCard:
    """Build a gallery from a ranked list of media FileNodes (e.g. a
    'photos of X' query) — not tied to one folder."""
    items = [media_item(session, n) for n in nodes if n.kind == "file"]
    return GalleryCard(folder_path=label, count=len(items), items=items)


def open_folder(session, folder: Path, *, gate: AccessGate, index,
                config: FilesConfig, indexer=None, index_queue=None) -> GalleryCard:
    """List a folder's contents for the UI **without blocking on indexing**.

    The grid is built from disk (one `walk`) plus a single batched lookup of
    any FileNodes that already exist. Media that isn't indexed yet still gets
    a `thumb_url` — `GET /files/thumb` generates thumbnails on miss — and is
    enqueued on `index_queue` so captions / entity links / persisted thumbs
    fill in in the background. `indexer` is accepted for call-site
    compatibility and no longer used here.
    """
    folder = folder.resolve()
    keys = index.authorized_keys(session)
    gate.assert_allowed(folder, registered_keys=keys)

    fkey = gate.key(folder)
    covered = fkey in keys or any(
        fkey.startswith(k.rstrip("/\\") + "/")
        or fkey.startswith(k.rstrip("/\\") + "\\")
        for k in keys
    )
    if not covered:
        # creates `pending` FileNode rows for every indexable file (incl. media)
        index.register(session, folder, gate, config)

    found = list(walk_dir(folder, config, gate, include_all=True))
    by_key: dict[str, m.FileNode] = {
        n.path_key: n
        for n in session.execute(
            select(m.FileNode).where(
                m.FileNode.path_key.in_([gate.key(fp.path) for fp in found])
            )
        ).scalars()
    }
    media_ids = [n.id for n in by_key.values() if n.media_kind]
    ents = _entities_for_many(session, media_ids)

    text_exts = {e.lower() for e in config.index_extensions}
    items: list[GalleryItem] = []
    to_index: list[str] = []
    for fp in found:
        qp = quote(str(fp.path))
        node = by_key.get(gate.key(fp.path))
        media = classify_media(fp.path.suffix, config)
        if media is not None:
            ready = node is not None and node.status == "ok"
            if not ready:
                to_index.append(str(fp.path))
            items.append(GalleryItem(
                path=str(fp.path),
                media_kind=(node.media_kind if node else None) or media,
                # generate-on-miss: a thumb URL is always safe to hand the UI
                thumb_url=f"/files/thumb?path={qp}",
                raw_url=f"/files/raw?path={qp}",
                has_thumb=bool(node and node.thumb_path),
                caption=node.caption if node else None,
                entities=ents.get(node.id, []) if node else [],
                captured_at=(node.captured_at if node and node.captured_at
                             else fp.mtime),
                size_bytes=fp.size,
                indexed=ready,
            ))
        else:
            items.append(GalleryItem(
                path=str(fp.path),
                media_kind="doc" if fp.path.suffix.lower() in text_exts else "file",
                raw_url=f"/files/raw?path={qp}",
                size_bytes=fp.size,
                indexed=False,
                captured_at=fp.mtime,
            ))

    if index_queue is not None and to_index:
        index_queue.enqueue_many(to_index)

    items.sort(key=lambda it: (
        it.captured_at is None,
        -(it.captured_at.timestamp()) if it.captured_at else 0,
        it.path,
    ))
    return GalleryCard(folder_path=str(folder), count=len(items), items=items)
