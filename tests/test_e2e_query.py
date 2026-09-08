import datetime as dt

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedRecord)
from io_assistant.db import models as m

STORE_DAY = dt.datetime(2026, 9, 1, 19, 0, tzinfo=dt.timezone.utc)
QUERY_DAY = dt.datetime(2026, 9, 8, 9, 0, tzinfo=dt.timezone.utc)  # Tuesday


def _stub_embedders(monkeypatch):
    stub = type("E", (), {"embed_one": lambda self, t: [0.0] * 768,
                          "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})
    import io_assistant.orchestrator as o
    monkeypatch.setattr(o, "Embedder", lambda cfg: stub())


@requires_db
def test_scenario_2_hangout_with_nafay(db, config, fake_backend, monkeypatch):
    _stub_embedders(monkeypatch)
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)

    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        records=[ExtractedRecord(kind="event", domain="social",
                                 title="dinner with Nafay at Arcadian",
                                 when_phrase="today", people=["Nafay"],
                                 places=["Arcadian"], confidence=0.9)]))
    o.handle("went out with Nafay to eat at Arcadian", captured_at=STORE_DAY)

    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [{"target_type": "record",
                          "kind_filter": ["event"], "entities": ["Nafay"],
                          "time_window": {"start": "last week", "end": "today"}}],
                          "answer_shape": "text"})
    fake_backend.set_answer("You had dinner with Nafay at Arcadian on Sep 1.")
    res = o.handle("Where have I hung out with Nafay in the past week?",
                   captured_at=QUERY_DAY)
    assert res.intent == "query" and "Nafay" in res.message


@requires_db
def test_scenario_3_what_work_today(db, config, fake_backend, monkeypatch):
    _stub_embedders(monkeypatch)
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    fake_backend.set_intent("store")

    for title, kind, domain, rec_phrase in [
        ("email the landlord", "task", "home", None),
        ("finish the Q3 deck", "task", "job", None),
        ("take out the trash", "chore", "home", "every Tuesday"),
    ]:
        fake_backend.set_extraction(ExtractionResult(records=[ExtractedRecord(
            kind=kind, domain=domain, title=title, status="open",
            recurrence_phrase=rec_phrase,
            when_phrase=None if rec_phrase else "today", confidence=0.9)]))
        o.handle(f"note: {title}", captured_at=QUERY_DAY)

    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [
        {"target_type": "record", "domain_filter": ["job"], "status_filter": ["open"],
         "time_window": {"start": None, "end": "today"}},
        {"target_type": "record", "kind_filter": ["chore"], "status_filter": ["open"]},
    ], "answer_shape": "markdown"})
    fake_backend.set_answer("- finish the Q3 deck\n- take out the trash")
    res = o.handle("What work do I have today?", captured_at=QUERY_DAY)
    assert res.intent == "query"
    assert "deck" in res.message and "trash" in res.message
