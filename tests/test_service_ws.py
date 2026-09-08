from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.service.app import create_app
from io_assistant.models_domain import ExtractionResult, ExtractedRecord
from io_assistant.db import models as m


@requires_db
def test_ws_roundtrip(config, fake_backend, db, monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(records=[
        ExtractedRecord(kind="note", title="ws note", confidence=0.9)]))
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind())
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"text": "note: ws note"})
            reply = ws.receive_json()
    assert reply["type"] == "answer" and reply["kind"] == "ack"
    assert db.query(m.Record).filter_by(title="ws note").count() == 1


@requires_db
def test_ws_bad_frame_keeps_open(config, fake_backend, db):
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind())
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_text("not json")
            reply = ws.receive_json()
    assert reply["type"] == "error"
