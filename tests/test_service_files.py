import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from tests.conftest import requires_db, StubEmbedder
from io_assistant.service.app import create_app
from io_assistant.config import FilesConfig


def _wipe_files(engine):
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE file_entity_links, file_edges, file_chunks, file_nodes "
            "RESTART IDENTITY CASCADE"
        ))


@pytest.fixture
def client_files(config, engine, tmp_path, fake_backend):
    config.files = FilesConfig(enabled=True, allowlist_roots=[str(tmp_path)])
    (tmp_path / "a.md").write_text("# A\nsome notes about pets")
    app = create_app(config, engine=engine)
    app.state.orchestrator._backend = fake_backend
    # keep the background indexer off the network in tests
    iq = app.state.index_queue
    if iq is not None:
        iq._indexer._backend = fake_backend
        iq._indexer._embed = StubEmbedder()
    _wipe_files(engine)
    with TestClient(app) as c:
        c.tmp = tmp_path
        yield c
    _wipe_files(engine)


@requires_db
def test_routes_404_when_disabled(config, engine):
    config.files = FilesConfig(enabled=False)
    with TestClient(create_app(config, engine=engine)) as c:
        assert c.get("/files").status_code == 404


@requires_db
def test_register_and_list(client_files):
    r = client_files.post("/files", json={"path": str(client_files.tmp)})
    assert r.status_code == 200 and r.json()["discovered"] == 1
    lst = client_files.get("/files").json()
    assert lst["enabled"] is True and lst["roots"]


@requires_db
def test_register_rejects_nonexistent_path(client_files):
    r = client_files.post("/files", json={"path": str(client_files.tmp / "no" / "such")})
    assert r.status_code == 400


@requires_db
def test_register_outside_allowlist_is_allowed(client_files, tmp_path):
    # Explicit registration self-authorizes — allowlist_roots only gate
    # phrase-resolved / implicit access.
    outside = tmp_path.parent / "io-outside-root"
    outside.mkdir(exist_ok=True)
    (outside / "note.md").write_text("hi")
    r = client_files.post("/files", json={"path": str(outside)})
    assert r.status_code == 200
    # and it's now readable
    c = client_files.get("/files/content", params={"path": str(outside / "note.md")})
    assert c.status_code == 200


@requires_db
def test_content_endpoint(client_files):
    client_files.post("/files", json={"path": str(client_files.tmp)})
    r = client_files.get("/files/content", params={"path": str(client_files.tmp / "a.md")})
    assert r.status_code == 200 and "pets" in r.json()["text"]


@requires_db
def test_forget(client_files):
    client_files.post("/files", json={"path": str(client_files.tmp)})
    r = client_files.request("DELETE", "/files", json={"path": str(client_files.tmp)})
    assert r.status_code == 200 and r.json()["forgotten"] >= 2
