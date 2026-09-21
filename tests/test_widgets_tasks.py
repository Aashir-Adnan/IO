import datetime as dt

from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.service.app import create_app
from io_assistant.widgets.tasks import alerts, pending_tasks

NOW = dt.datetime(2026, 9, 22, 15, 30, tzinfo=dt.timezone.utc)
DAY = dt.timedelta(days=1)


def _utt(db):
    u = m.Utterance(text="s", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    return u


def rec(db, u, title, *, due=None, kind="task", status="open", created=NOW):
    r = m.Record(kind=kind, title=title, status=status, due_at=due, attributes={},
                 source_utterance_id=u.id, created_at=created)
    db.add(r)
    db.flush()
    return r


@requires_db
def test_pending_tasks_are_ordered_and_grouped(db):
    u = _utt(db)
    rec(db, u, "someday", due=None)
    rec(db, u, "next week", due=NOW + 5 * DAY)
    rec(db, u, "today", due=NOW.replace(hour=0, minute=0))          # bare task: due today 00:00
    rec(db, u, "overdue", due=NOW - 3 * DAY)
    rec(db, u, "tomorrow chore", due=NOW + DAY, kind="chore")
    rec(db, u, "finished", due=NOW - DAY, status="done")            # excluded
    rec(db, u, "a note", due=NOW, kind="note")                       # excluded
    out = pending_tasks(db, NOW)
    assert [t["title"] for t in out] == [
        "overdue", "today", "tomorrow chore", "next week", "someday"]
    assert [t["group"] for t in out] == ["overdue", "today", "upcoming", "upcoming", "none"]
    assert out[0]["due_label"] == "3 days ago" and out[1]["due_label"] == "Today"
    assert out[-1]["due_label"] is None and out[-1]["due_at"] is None


@requires_db
def test_a_task_due_earlier_today_is_not_overdue(db):
    u = _utt(db)
    rec(db, u, "bare task", due=NOW.replace(hour=0, minute=0))
    (t,) = pending_tasks(db, NOW)
    assert t["group"] == "today"


@requires_db
def test_pending_tasks_respects_the_limit(db):
    u = _utt(db)
    for i in range(5):
        rec(db, u, f"t{i}", due=NOW + i * DAY)
    assert len(pending_tasks(db, NOW, limit=3)) == 3


@requires_db
def test_alerts_summarise_overdue_today_and_occasions(db):
    u = _utt(db)
    rec(db, u, "pay rent", due=NOW - 2 * DAY)
    rec(db, u, "call bank", due=NOW - DAY)
    rec(db, u, "gym", due=NOW)
    db.add(m.Occasion(name="Eid", date=(NOW + 3 * DAY).date()))
    db.add(m.Occasion(name="Far away", date=(NOW + 30 * DAY).date()))
    db.flush()
    out = alerts(db, NOW)
    assert [a["kind"] for a in out] == ["overdue", "today", "occasion"]
    assert out[0]["text"] == "2 overdue tasks" and "pay rent" in out[0]["detail"]
    assert out[1]["text"] == "1 task today"
    assert out[2]["text"] == "Eid in 3 days"


@requires_db
def test_alerts_are_empty_when_all_is_quiet(db):
    assert alerts(db, NOW) == []


@requires_db
def test_endpoints(config, db):
    u = _utt(db)
    rec(db, u, "pay rent", due=dt.datetime.now(dt.timezone.utc) - 2 * DAY)
    app = create_app(config, orchestrator=object(), engine=db.get_bind(),
                     conversations=object(), voice=object())
    with TestClient(app) as c:
        tasks = c.get("/tasks").json()
        assert [t["title"] for t in tasks] == ["pay rent"] and tasks[0]["group"] == "overdue"
        assert c.get("/alerts").json()[0]["kind"] == "overdue"
