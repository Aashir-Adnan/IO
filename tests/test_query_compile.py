import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.query.plan import SubQuery, TimeWindow
from io_assistant.query.compile import compile_count, compile_structured

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)
EMPTY = {"person": [], "place": [], "item": [], "occasion": []}


def _utt(db):
    u = m.Utterance(text="seed", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    return u.id


@requires_db
def test_compile_filters_kind_and_window(db):
    uid = _utt(db)
    db.add_all([
        m.Record(kind="event", title="dinner", occurred_at=NOW - dt.timedelta(days=2),
                 attributes={}, source_utterance_id=uid),
        m.Record(kind="event", title="old dinner", occurred_at=NOW - dt.timedelta(days=90),
                 attributes={}, source_utterance_id=uid),
        m.Record(kind="task", title="a task", due_at=NOW, attributes={},
                 source_utterance_id=uid),
    ])
    db.flush()
    sq = SubQuery(target_type="record", kind_filter=["event"],
                  time_window=TimeWindow(start=NOW - dt.timedelta(days=7), end=NOW))
    rows = db.execute(compile_structured(sq, EMPTY, NOW)).scalars().all()
    assert {r.title for r in rows} == {"dinner"}


@requires_db
def test_overdue_open_task_is_in_a_today_window(db):
    uid = _utt(db)
    old = m.Record(kind="task", title="overdue thing", status="open",
                   due_at=NOW - dt.timedelta(days=3), attributes={},
                   source_utterance_id=uid)
    db.add(old)
    db.flush()
    sq = SubQuery(target_type="record", status_filter=["open"],
                  time_window=TimeWindow(start=NOW.replace(hour=0, minute=0),
                                         end=NOW.replace(hour=23, minute=59)))
    rows = db.execute(compile_structured(sq, EMPTY, NOW)).scalars().all()
    assert old.id in {r.id for r in rows}


@requires_db
def test_last_week_query_does_not_pull_an_open_overdue_task(db):
    uid = _utt(db)
    t = m.Record(kind="task", title="pay rent", status="open",
                 due_at=NOW - dt.timedelta(days=2), attributes={},
                 source_utterance_id=uid)
    e = m.Record(kind="event", title="museum",
                 occurred_at=NOW - dt.timedelta(days=9), attributes={},
                 source_utterance_id=uid)
    db.add_all([t, e])
    db.flush()
    sq = SubQuery(target_type="record",
                  time_window=TimeWindow(start=NOW - dt.timedelta(days=14),
                                         end=NOW - dt.timedelta(days=7)))
    rows = db.execute(compile_structured(sq, EMPTY, NOW)).scalars().all()
    ids = {r.id for r in rows}
    assert e.id in ids and t.id not in ids


@requires_db
def test_done_overdue_task_still_obeys_the_window(db):
    uid = _utt(db)
    d = m.Record(kind="task", title="done long ago", status="done",
                 due_at=NOW - dt.timedelta(days=30), attributes={},
                 source_utterance_id=uid)
    db.add(d)
    db.flush()
    sq = SubQuery(target_type="record", status_filter=["open", "done"],
                  time_window=TimeWindow(start=NOW.replace(hour=0, minute=0),
                                         end=NOW.replace(hour=23, minute=59)))
    rows = db.execute(compile_structured(sq, EMPTY, NOW)).scalars().all()
    assert d.id not in {r.id for r in rows}


@requires_db
def test_compile_entity_link_exists(db):
    uid = _utt(db)
    p = m.Person(canonical_name="Nafay", aliases=[])
    db.add(p)
    db.flush()
    r1 = m.Record(kind="event", title="with nafay", occurred_at=NOW, attributes={},
                  source_utterance_id=uid)
    r2 = m.Record(kind="event", title="alone", occurred_at=NOW, attributes={},
                  source_utterance_id=uid)
    db.add_all([r1, r2])
    db.flush()
    db.add(m.RecordPerson(record_id=r1.id, person_id=p.id))
    db.flush()
    sq = SubQuery(target_type="record", entities=["Nafay"])
    rows = db.execute(compile_structured(
        sq, {"person": [p.id], "place": [], "item": [], "occasion": []}, NOW
    )).scalars().all()
    assert {r.title for r in rows} == {"with nafay"}


@requires_db
def test_compile_count_matches_the_same_filters(db):
    uid = _utt(db)
    db.add_all([
        m.Record(kind="watchlist", title="film a", status="open", attributes={},
                 source_utterance_id=uid),
        m.Record(kind="watchlist", title="film b", status="open", attributes={},
                 source_utterance_id=uid),
        m.Record(kind="watchlist", title="film c", status="done", attributes={},
                 source_utterance_id=uid),
        m.Record(kind="task", title="unrelated", attributes={},
                 source_utterance_id=uid),
    ])
    db.flush()
    sq = SubQuery(target_type="record", kind_filter=["watchlist"])
    n = db.execute(compile_count(sq, EMPTY, NOW)).scalar_one()
    assert n == 3


@requires_db
def test_compile_count_respects_the_roll_forward_window(db):
    """The time-window + roll-forward OR-clause is copied into compile_count
    (not shared via _conds) — this locks the two functions together so a
    "how many tasks are due" count matches what the list view would show,
    including an overdue-but-open task outside the literal window."""
    uid = _utt(db)
    overdue = m.Record(kind="task", title="overdue thing", status="open",
                       due_at=NOW - dt.timedelta(days=3), attributes={},
                       source_utterance_id=uid)
    in_window = m.Record(kind="task", title="today thing", status="open",
                         due_at=NOW, attributes={}, source_utterance_id=uid)
    out_of_window_closed = m.Record(kind="task", title="done long ago", status="done",
                                    due_at=NOW - dt.timedelta(days=30), attributes={},
                                    source_utterance_id=uid)
    # Open, but neither in the literal window nor overdue (due in the
    # future) — must be excluded by the window on both sides. Without the
    # roll-forward OR-clause actually running inside compile_count, this
    # record would be miscounted as included (a "how many" call ignoring
    # time_window entirely, per the bug the test guards against).
    future_open = m.Record(kind="task", title="future thing", status="open",
                           due_at=NOW + dt.timedelta(days=10), attributes={},
                           source_utterance_id=uid)
    db.add_all([overdue, in_window, out_of_window_closed, future_open])
    db.flush()
    sq = SubQuery(target_type="record", status_filter=["open"],
                  time_window=TimeWindow(start=NOW.replace(hour=0, minute=0),
                                         end=NOW.replace(hour=23, minute=59)))
    rows = db.execute(compile_structured(sq, EMPTY, NOW)).scalars().all()
    n = db.execute(compile_count(sq, EMPTY, NOW)).scalar_one()
    assert n == len(rows) == 2
    assert {r.id for r in rows} == {overdue.id, in_window.id}
