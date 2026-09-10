import datetime as dt

from io_assistant.db import models as m
from io_assistant.tasks.complete import CloseOutcome, close_record, set_record_status
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


CK = {"task", "chore"}


def _task(db, title, status="open", kind="task"):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    r = m.Record(kind=kind, title=title, status=status, source_utterance_id=u.id)
    db.add(r); db.flush()
    return r


@requires_db
def test_close_record_matches_the_one_open_task(db):
    r = _task(db, "buy groceries for the week")
    out = close_record(db, "groceries", NOW, checkable_kinds=CK)
    assert out.status == "matched" and out.record.id == r.id


@requires_db
def test_close_record_ambiguous_when_two_plausible(db):
    _task(db, "call the dentist")
    _task(db, "book the dentist follow-up")
    out = close_record(db, "the dentist thing", NOW, checkable_kinds=CK)
    assert out.status == "ambiguous" and len(out.candidates) >= 2


@requires_db
def test_close_record_none_when_nothing_open_matches(db):
    _task(db, "buy groceries", status="done")
    _task(db, "renew passport")
    out = close_record(db, "the laundry", NOW, checkable_kinds=CK)
    assert out.status == "none"


@requires_db
def test_close_record_ignores_non_checkable_kinds(db):
    _task(db, "watched Dune", kind="watchlist")   # not in CK
    out = close_record(db, "Dune", NOW, checkable_kinds=CK)
    assert out.status == "none"
