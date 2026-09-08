from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.conversation.store import ConversationStore
from io_assistant.service.app import create_app
from io_assistant.db import models as m


def _stub(monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())


@requires_db
def test_two_turns_persist_and_follow_up_has_context(config, fake_backend, db, monkeypatch):
    _stub(monkeypatch)
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    store = ConversationStore(lambda: db)
    app = create_app(config, orchestrator=o, engine=db.get_bind(), conversations=store)

    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [], "answer_shape": "text"})
    with TestClient(app) as c:
        r1 = c.post("/utterance", json={"text": "where did I see Nafay?"})
        cid = r1.json()["conversation_id"]
        assert r1.json()["kind"] in ("answer", "unknown")
        c.post("/utterance", json={"text": "and last week?", "conversation_id": cid})

    assert "Nafay" in (fake_backend.last_context or "")
    assert db.query(m.Message).filter_by(conversation_id=cid).count() == 4

    with TestClient(app) as c:
        hist = c.get("/conversation", params={"id": cid}).json()["messages"]
    assert len(hist) == 4
    assert [msg["role"] for msg in hist] == ["assistant", "user", "assistant", "user"]
    assert hist[1]["text"] == "and last week?"  # newest first


@requires_db
def test_new_conversation_and_list(config, fake_backend, db):
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind(),
                     conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        new = c.post("/conversation").json()["conversation_id"]
        c.post("/utterance", json={"text": "hello there", "conversation_id": new})
        convs = c.get("/conversations").json()
    assert any(cv["id"] == new and cv["title"] == "hello there" for cv in convs)
