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


@requires_db
def test_open_folder_lists_media_and_registers(db, config, fake_backend, tmp_path):
    album = tmp_path / "Hunza"
    album.mkdir()
    shutil.copy(FX / "pic.jpg", album / "a.jpg")
    (album / "notes.txt").write_text("not media")
    cfg, gate, index, indexer = _ctx(config, fake_backend, tmp_path)
    card = open_folder(db, album, gate=gate, indexer=indexer, index=index, config=cfg)
    db.flush()
    assert card.type == "gallery" and card.count == 1
    assert card.items[0].path.endswith("a.jpg")
    assert card.items[0].thumb_url and "path=" in card.items[0].thumb_url
    assert db.query(m.FileNode).filter_by(registered_root=True).count() == 1


@requires_db
def test_open_folder_carries_caption_entities(db, config, fake_backend, tmp_path):
    album = tmp_path / "Hunza"
    album.mkdir()
    shutil.copy(FX / "pic.jpg", album / "a.jpg")
    cfg, gate, index, indexer = _ctx(config, fake_backend, tmp_path)
    open_folder(db, album, gate=gate, indexer=indexer, index=index, config=cfg)
    db.flush()
    node = db.query(m.FileNode).filter_by(media_kind="image").one()
    p = m.Person(canonical_name="Nafay", aliases=[])
    db.add(p)
    db.flush()
    db.add(m.FileEntityLink(file_id=node.id, etype="person", entity_id=p.id,
                            source="caption"))
    node.caption = "me and Nafay"
    db.flush()
    card = open_folder(db, album, gate=gate, indexer=indexer, index=index, config=cfg)
    item = card.items[0]
    assert item.caption == "me and Nafay"
    assert item.entities and item.entities[0].name == "Nafay"
