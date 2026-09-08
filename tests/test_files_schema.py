from tests.conftest import requires_db
from io_assistant.config import FilesConfig, load_config
from io_assistant.db import models as m
from io_assistant.models_domain import Intent, FilesCard, FileHit, Card


def test_files_config_defaults():
    c = FilesConfig()
    assert c.enabled is False
    assert c.max_file_bytes == 2_000_000
    assert ".pdf" in c.index_extensions
    assert ".jpg" in c.media_extensions
    assert any("node_modules" in g for g in c.exclude_globs)
    assert c.retrieval_file_limit == 6


def test_config_has_files_block():
    assert isinstance(load_config().files, FilesConfig)


def test_intent_includes_file():
    assert "file" in getattr(Intent, "__args__", ())


def test_files_card_shape():
    card = FilesCard(hits=[FileHit(path="/x/a.md", title="A", why="matches x")])
    assert card.type == "files"
    assert card.model_dump()["hits"][0]["path"] == "/x/a.md"


@requires_db
def test_file_captions_table_and_thumb_path(db):
    from io_assistant.db import models as m
    n = m.FileNode(path="/m/pic.jpg", path_key="/m/pic.jpg", kind="file",
                   media_kind="image", status="ok", thumb_path="/t/abc.webp")
    db.add(n)
    db.flush()
    assert n.thumb_path == "/t/abc.webp"
    db.add(m.FileCaption(file_id=n.id, text="me and Nafay", source="text"))
    db.flush()
    assert db.query(m.FileCaption).one().text == "me and Nafay"


@requires_db
def test_file_tables_exist(db):
    n = m.FileNode(path="/tmp/a.md", path_key="/tmp/a.md", kind="file",
                   status="pending")
    db.add(n)
    db.flush()
    assert n.id is not None
    db.add(m.FileChunk(file_id=n.id, ord=0, text="hello world",
                       token_estimate=2, embedding=[0.0] * 768))
    db.add(m.FileEdge(src_id=n.id, dst_id=n.id, rel="contains"))
    db.add(m.FileEntityLink(file_id=n.id, etype="person", entity_id=1))
    db.flush()
