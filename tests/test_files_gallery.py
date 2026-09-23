import shutil
from pathlib import Path

from tests.conftest import requires_db, StubEmbedder
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.index import FileIndexer
from io_assistant.files.gallery import open_folder
from io_assistant.db import models as m

FX = Path(__file__).parent / "fixtures" / "files"


def _ctx(config, fake_backend, tmp_path):
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)],
                      thumbs_dir=str(tmp_path / "thumbs"))
    gate = AccessGate(cfg)
    return (cfg, gate, FileIndex(lambda: None),
            FileIndexer(StubEmbedder(), fake_backend, cfg, config.resolver))


class _FakeQueue:
    def __init__(self):
        self.queued: list[str] = []

    def enqueue_many(self, paths):
        self.queued.extend(paths)


@requires_db
def test_open_folder_lists_all_files_and_defers_indexing(db, config, fake_backend, tmp_path):
    album = tmp_path / "Hunza"
    album.mkdir()
    shutil.copy(FX / "pic.jpg", album / "a.jpg")
    (album / "notes.txt").write_text("a document")
    (album / "archive.zip").write_bytes(b"PK\x03\x04nope")   # unindexable extension
    cfg, gate, index, indexer = _ctx(config, fake_backend, tmp_path)
    q = _FakeQueue()
    card = open_folder(db, album, gate=gate, index=index, config=cfg, index_queue=q)
    db.flush()
    assert card.type == "gallery" and card.count == 3
    by_name = {Path(it.path).name: it for it in card.items}
    # media is listed immediately, thumb URL always present (generate-on-miss),
    # but not yet indexed — it's been handed to the background queue instead
    assert by_name["a.jpg"].media_kind == "image"
    assert by_name["a.jpg"].indexed is False
    assert by_name["a.jpg"].thumb_url and "path=" in by_name["a.jpg"].thumb_url
    assert str(album / "a.jpg") in q.queued
    assert by_name["notes.txt"].media_kind == "doc" and by_name["notes.txt"].indexed is False
    assert by_name["archive.zip"].media_kind == "file" and by_name["archive.zip"].indexed is False
    assert by_name["archive.zip"].raw_url and by_name["archive.zip"].size_bytes
    assert db.query(m.FileNode).filter_by(registered_root=True).count() == 1


@requires_db
def test_open_folder_no_queue_still_lists(db, config, fake_backend, tmp_path):
    album = tmp_path / "Hunza"
    album.mkdir()
    shutil.copy(FX / "pic.jpg", album / "a.jpg")
    cfg, gate, index, indexer = _ctx(config, fake_backend, tmp_path)
    card = open_folder(db, album, gate=gate, index=index, config=cfg)
    assert card.count == 1 and card.items[0].media_kind == "image"


@requires_db
def test_open_folder_carries_caption_entities(db, config, fake_backend, tmp_path):
    album = tmp_path / "Hunza"
    album.mkdir()
    shutil.copy(FX / "pic.jpg", album / "a.jpg")
    cfg, gate, index, indexer = _ctx(config, fake_backend, tmp_path)
    open_folder(db, album, gate=gate, index=index, config=cfg)
    db.flush()
    node = db.query(m.FileNode).filter_by(media_kind="image").one()
    p = m.Person(canonical_name="Nafay", aliases=[])
    db.add(p)
    db.flush()
    db.add(m.FileEntityLink(file_id=node.id, etype="person", entity_id=p.id,
                            source="caption"))
    node.caption = "me and Nafay"
    db.flush()
    card = open_folder(db, album, gate=gate, index=index, config=cfg)
    item = card.items[0]
    assert item.caption == "me and Nafay"
    assert item.entities and item.entities[0].name == "Nafay"
