import pytest
from fastapi.testclient import TestClient

from tests.conftest import requires_db, StubEmbedder
from io_assistant.service.app import create_app
from io_assistant.config import FilesConfig


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
    with TestClient(app) as c:
        c.tmp = tmp_path
        yield c


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
def test_register_denied_path(client_files):
    r = client_files.post("/files", json={"path": "/etc"})
    assert r.status_code == 400


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
