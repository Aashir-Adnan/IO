import datetime as dt

from io_assistant.db import models as m
from io_assistant.tasks.complete import set_record_status
from tests.conftest import requires_db

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


@requires_db
def test_set_record_status_done_stamps_completed_at(db):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    r = m.Record(kind="task", title="buy milk", status="open",
                 source_utterance_id=u.id)
    db.add(r); db.flush()

    set_record_status(db, r, "done", NOW)
    assert r.status == "done" and r.completed_at == NOW

    set_record_status(db, r, "open", NOW)
    assert r.status == "open" and r.completed_at is None
