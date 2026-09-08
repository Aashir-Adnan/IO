from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select

from io_assistant.config import FilesConfig
from io_assistant.db import models as m
from io_assistant.files.paths import AccessGate
from io_assistant.files.walk import classify_media, walk_dir
from io_assistant.models_domain import EntityRef, GalleryCard, GalleryItem

__all__ = ["open_folder"]

_ENTITY_NAME = {
    "person": m.Person.canonical_name, "place": m.Place.name,
    "item": m.Item.name, "occasion": m.Occasion.name,
}
_ENTITY_MODEL = {
    "person": m.Person, "place": m.Place, "item": m.Item, "occasion": m.Occasion,
}


def _entities_for(session, file_id: int) -> list[EntityRef]:
    out: list[EntityRef] = []
    for etype, model in _ENTITY_MODEL.items():
        for eid, name in session.execute(
            select(model.id, _ENTITY_NAME[etype])
            .join(m.FileEntityLink, m.FileEntityLink.entity_id == model.id)
            .where(m.FileEntityLink.file_id == file_id,
                   m.FileEntityLink.etype == etype)
        ).all():
            out.append(EntityRef(etype=etype, id=eid, name=name))
    return out


def open_folder(session, folder: Path, *, gate: AccessGate, indexer, index,
                config: FilesConfig) -> GalleryCard:
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
        index.register(session, folder, gate, config)

    media_nodes = []
    for fp in walk_dir(folder, config, gate):
        if classify_media(fp.path.suffix, config) is None:
            continue
        media_nodes.append(indexer.index_path(session, fp.path, gate=gate))

    items: list[GalleryItem] = []
    for n in media_nodes:
        qp = quote(n.path)
        items.append(GalleryItem(
            path=n.path,
            media_kind=n.media_kind or "image",
            thumb_url=(f"/files/thumb?path={qp}" if n.thumb_path else None),
            raw_url=f"/files/raw?path={qp}",
            has_thumb=n.thumb_path is not None,
            caption=n.caption,
            entities=_entities_for(session, n.id),
            captured_at=n.captured_at,
        ))
    items.sort(key=lambda it: (
        it.captured_at is None,
        -(it.captured_at.timestamp()) if it.captured_at else 0,
        it.path,
    ))
    return GalleryCard(folder_path=str(folder), count=len(items), items=items)
