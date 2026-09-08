import datetime as dt

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)


def _stub_embedders(monkeypatch):
    stub = type("E", (), {"embed_one": lambda self, t: [0.0] * 768,
                          "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})
    import io_assistant.orchestrator as o
    monkeypatch.setattr(o, "Embedder", lambda cfg: stub())


@requires_db
def test_query_intent_answers_and_logs(db, config, fake_backend, monkeypatch):
    _stub_embedders(monkeypatch)
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    db.add(m.Record(kind="task", domain="job", title="finish the report",
                    status="open", due_at=NOW, attributes={},
                    source_utterance_id=u.id))
    db.flush()

    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [{"target_type": "record",
                          "domain_filter": ["job"], "status_filter": ["open"]}],
                          "answer_shape": "markdown"})
    fake_backend.set_answer("- finish the report (due today)")

    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("what work do I have today?", captured_at=NOW)
    assert res.intent == "query"
    assert "report" in res.message
    assert db.query(m.Utterance).filter_by(resolved_intent="query").count() == 1
