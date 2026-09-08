import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.query.plan import SubQuery, TimeWindow
from io_assistant.query.compile import compile_structured

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
