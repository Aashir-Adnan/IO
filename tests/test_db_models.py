import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m


@requires_db
def test_insert_utterance_and_record_with_links(db):
    u = m.Utterance(text="dinner at Arcadian", source="text",
                    captured_at=dt.datetime.now(dt.timezone.utc))
    db.add(u); db.flush()
    p = m.Person(canonical_name="Nafay", aliases=["nafay"])
    place = m.Place(name="Arcadian", type="restaurant", aliases=[])
    db.add_all([p, place]); db.flush()
    r = m.Record(kind="event", domain="social", title="dinner",
                 occurred_at=dt.datetime.now(dt.timezone.utc),
                 attributes={"occasion": "birthday"}, source_utterance_id=u.id)
    db.add(r); db.flush()
    db.add(m.RecordPerson(record_id=r.id, person_id=p.id))
    db.add(m.RecordPlace(record_id=r.id, place_id=place.id))
    db.flush()
    got = db.get(m.Record, r.id)
    assert got.attributes["occasion"] == "birthday"
    assert got.kind == "event"
    assert db.query(m.RecordPerson).filter_by(record_id=r.id).count() == 1


@requires_db
def test_record_accepts_arbitrary_kind(db):
    u = m.Utterance(text="gym leg day", source="text",
                    captured_at=dt.datetime.now(dt.timezone.utc))
    db.add(u); db.flush()
    r = m.Record(kind="gym_session", domain="health", title="leg day",
                 occurred_at=dt.datetime.now(dt.timezone.utc), source_utterance_id=u.id)
    db.add(r); db.flush()
    assert db.get(m.Record, r.id).kind == "gym_session"
