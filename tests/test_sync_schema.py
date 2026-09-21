import datetime as dt

from sqlalchemy import text

from tests.conftest import requires_db
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 22, 12, 0, tzinfo=dt.timezone.utc)


def _utt(db):
    u = m.Utterance(text="s", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    return u


@requires_db
def test_new_rows_get_distinct_sync_ids_and_are_unsynced(db):
    a = m.Person(canonical_name="A", aliases=[])
    b = m.Person(canonical_name="B", aliases=[])
    db.add_all([a, b])
    db.flush()
    assert a.sync_id and b.sync_id and a.sync_id != b.sync_id
    assert a.synced_at is None


@requires_db
def test_deleting_a_synced_row_writes_one_tombstone(db):
    p = m.Person(canonical_name="Gone", aliases=[])
    db.add(p)
    db.flush()
    sid = p.sync_id
    db.delete(p)
    db.flush()
    t = db.query(m.SyncTombstone).one()
    assert (t.table_name, t.sync_id, t.synced_at) == ("people", sid, None)


@requires_db
def test_no_tombstone_while_applying_remote_changes(db):
    p = m.Person(canonical_name="Remote", aliases=[])
    db.add(p)
    db.flush()
    db.info["sync_applying"] = True
    db.delete(p)
    db.flush()
    assert db.query(m.SyncTombstone).count() == 0


@requires_db
def test_record_delete_cascades_links_without_extra_tombstones(db):
    u = _utt(db)
    p = m.Person(canonical_name="Ali", aliases=[])
    r = m.Record(kind="note", title="x", attributes={}, source_utterance_id=u.id)
    db.add_all([p, r])
    db.flush()
    db.add(m.RecordPerson(record_id=r.id, person_id=p.id))
    db.flush()
    db.delete(r)
    db.flush()
    rows = db.query(m.SyncTombstone).all()
    assert [t.table_name for t in rows] == ["records"]


@requires_db
def test_link_rows_start_unsynced(db):
    u = _utt(db)
    p = m.Person(canonical_name="Ali", aliases=[])
    r = m.Record(kind="note", title="x", attributes={}, source_utterance_id=u.id)
    db.add_all([p, r])
    db.flush()
    link = m.RecordPerson(record_id=r.id, person_id=p.id)
    db.add(link)
    db.flush()
    assert link.synced_at is None


@requires_db
def test_message_updated_at_moves_on_update(db):
    c = m.Conversation()
    db.add(c)
    db.flush()
    msg = m.Message(conversation_id=c.id, role="user", text="hi")
    db.add(msg)
    db.flush()
    db.execute(text("UPDATE messages SET updated_at = '2020-01-01' WHERE id = :i"), {"i": msg.id})
    db.refresh(msg)
    msg.text = "edited"
    db.flush()
    db.refresh(msg)
    assert msg.updated_at.year >= 2026


@requires_db
def test_alias_and_state_tables_round_trip(db):
    db.add(m.SyncAlias(alias="11111111-1111-1111-1111-111111111111",
                       canonical="22222222-2222-2222-2222-222222222222"))
    db.add(m.SyncState(key="seq", value={"n": 3}))
    db.flush()
    assert db.get(m.SyncState, "seq").value == {"n": 3}
    assert db.query(m.SyncAlias).one().canonical.startswith("2222")
