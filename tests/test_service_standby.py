import datetime as dt

from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.conversation.store import ConversationStore
from io_assistant.service.app import create_app
from io_assistant.db import models as m

NOW = dt.datetime.now(dt.timezone.utc)


@requires_db
def test_standby_panel(config, fake_backend, db):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    db.add(m.Record(kind="task", domain="job", title="finish deck", status="open",
                    due_at=NOW + dt.timedelta(hours=2), attributes={},
                    source_utterance_id=u.id))
    db.add(m.Occasion(name="Priya's birthday",
                      date=(NOW + dt.timedelta(days=11)).date()))
    db.flush()
    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        sb = c.get("/standby").json()
    assert sb["stats"]["memories"] >= 1
    texts = " ".join(ch["text"] for ch in sb["chips"])
    assert "task" in texts and "Priya" in texts
