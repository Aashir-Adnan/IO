import datetime as dt

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedRecord)
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 8, 20, 0, tzinfo=dt.timezone.utc)


def _stub_embedder(monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())


@requires_db
def test_store_uses_acknowledge_and_builds_cards(db, config, fake_backend, monkeypatch):
    _stub_embedder(monkeypatch)
    fake_backend.set_intent("store")
    fake_backend.set_ack("Logged dinner with Nafay at Arcadian this evening.")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        records=[ExtractedRecord(kind="event", domain="social",
                                 title="dinner with Nafay", when_phrase="today",
                                 people=["Nafay"], places=["Arcadian"], confidence=0.9)]))
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("dinner with Nafay at Arcadian",
                   history="you: hi\nio: hello", captured_at=NOW)

    assert res.message == "Logged dinner with Nafay at Arcadian this evening."
    assert res.intent_kind == "ack"
    assert "hi" in fake_backend.last_context
    assert [c.type for c in res.cards] == ["record"]
    card = res.cards[0]
    assert card.title == "dinner with Nafay"
    assert {e.name for e in card.entities} == {"Nafay", "Arcadian"}


@requires_db
def test_query_builds_sources_card(db, config, fake_backend, monkeypatch):
    _stub_embedder(monkeypatch)
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    db.add(m.Record(kind="task", domain="job", title="finish the deck", status="open",
                    due_at=NOW, attributes={}, source_utterance_id=u.id))
    db.flush()
    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [{"target_type": "record",
                          "kind_filter": ["task"], "status_filter": ["open"]}],
                          "answer_shape": "markdown"})
    fake_backend.set_answer("- finish the deck")
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("what tasks do I have?", history="", captured_at=NOW)
    types = {c.type for c in res.cards}
    assert "sources" in types
    assert res.intent_kind == "answer"
