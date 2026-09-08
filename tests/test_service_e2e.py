from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.service.app import create_app
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedRecord)
from io_assistant.db import models as m


@requires_db
def test_store_then_query_over_http(config, fake_backend, db, monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind())

    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        records=[ExtractedRecord(kind="event", domain="social",
                                 title="dinner with Nafay", when_phrase="today",
                                 people=["Nafay"], places=["Arcadian"],
                                 confidence=0.9)]))
    with TestClient(app) as c:
        r1 = c.post("/utterance", json={"text": "dinner with Nafay at Arcadian"})
        assert r1.json()["stored"] is True

        fake_backend.set_intent("query")
        fake_backend.set_plan({"subqueries": [{"target_type": "record",
                              "kind_filter": ["event"], "entities": ["Nafay"]}],
                              "answer_shape": "text"})
        fake_backend.set_answer("You had dinner with Nafay at Arcadian.")
        r2 = c.post("/utterance", json={"text": "when did I see Nafay?"})
    assert r2.json()["intent"] == "query"
    assert "Nafay" in r2.json()["message"]
    assert db.query(m.Record).filter_by(title="dinner with Nafay").count() == 1
