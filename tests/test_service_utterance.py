from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.service.app import create_app
from io_assistant.models_domain import ExtractionResult, ExtractedRecord
from io_assistant.db import models as m


def _stub_embedder(monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())


@requires_db
def test_post_utterance_stores(config, fake_backend, db, monkeypatch):
    _stub_embedder(monkeypatch)
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(records=[
        ExtractedRecord(kind="note", title="buy milk", confidence=0.9)]))
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind())
    with TestClient(app) as c:
        r = c.post("/utterance", json={"text": "note: buy milk"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "store" and body["kind"] == "ack"
    assert db.query(m.Record).filter_by(title="buy milk").count() == 1


@requires_db
def test_post_utterance_gate_then_confirm(config, fake_backend, db, monkeypatch):
    _stub_embedder(monkeypatch)
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(records=[
        ExtractedRecord(kind="note", title="vague thing", confidence=0.2)]))
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind())
    with TestClient(app) as c:
        r1 = c.post("/utterance", json={"text": "maybe something"})
        tok = r1.json()["pending_token"]
        assert tok
        r2 = c.post("/utterance", json={"text": "yes", "confirm_token": tok})
    assert r2.json()["kind"] == "ack"
    assert db.query(m.Record).filter_by(title="vague thing").count() == 1
