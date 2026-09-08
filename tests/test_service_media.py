import shutil
from pathlib import Path

import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from tests.conftest import requires_db, StubEmbedder
from io_assistant.service.app import create_app
from io_assistant.config import FilesConfig
from io_assistant.models_domain import ExtractionResult, ExtractedPerson

FX = Path(__file__).resolve().parents[0] / "fixtures" / "files"


def _wipe(engine):
    with engine.begin() as c:
        c.execute(text("TRUNCATE file_captions, file_entity_links, file_edges, "
                       "file_chunks, file_nodes RESTART IDENTITY CASCADE"))


@pytest.fixture
def mclient(config, engine, tmp_path, fake_backend):
    config.files = FilesConfig(enabled=True, allowlist_roots=[str(tmp_path)],
                               thumbs_dir=str(tmp_path / "thumbs"))
    album = tmp_path / "Hunza"
    album.mkdir()
    shutil.copy(FX / "pic.jpg", album / "a.jpg")
    app = create_app(config, engine=engine)
    app.state.orchestrator._backend = fake_backend
    app.state.orchestrator._embedder = StubEmbedder()
    iq = app.state.index_queue
    if iq:
        iq._indexer._backend = fake_backend
        iq._indexer._embed = StubEmbedder()
    _wipe(engine)
    with TestClient(app) as c:
        c.tmp = tmp_path
        yield c
    _wipe(engine)


@requires_db
def test_open_then_raw_range(mclient):
    r = mclient.post("/files/open", json={"path": str(mclient.tmp / "Hunza")})
    assert r.status_code == 200
    item = r.json()["items"][0]
    raw = mclient.get(item["raw_url"], headers={"Range": "bytes=0-9"})
    assert raw.status_code == 206
    assert raw.headers["content-range"].startswith("bytes 0-9/")


@requires_db
def test_thumb_served(mclient):
    item = mclient.post("/files/open",
                        json={"path": str(mclient.tmp / "Hunza")}).json()["items"][0]
    t = mclient.get(item["thumb_url"])
    assert t.status_code == 200 and t.headers["content-type"] == "image/webp"


@requires_db
def test_open_phrase_not_found(mclient):
    r = mclient.post("/files/open", json={"phrase": "no such album"})
    assert r.status_code == 404


@requires_db
def test_caption_links_entities(mclient):
    mclient.post("/files/open", json={"path": str(mclient.tmp / "Hunza")})
    mclient.app.state.orchestrator._backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)]))
    p = str(mclient.tmp / "Hunza" / "a.jpg")
    r = mclient.post("/files/caption", json={"path": p, "text": "me and Nafay"})
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is False
    assert body["entities"][0]["name"] == "Nafay"


@requires_db
def test_media_routes_404_when_disabled(config, engine):
    config.files = FilesConfig(enabled=False)
    with TestClient(create_app(config, engine=engine)) as c:
        assert c.post("/files/open", json={"path": "/x"}).status_code == 404
        assert c.get("/files/raw", params={"path": "/x"}).status_code == 404
