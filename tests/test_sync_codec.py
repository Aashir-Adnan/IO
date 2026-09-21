import datetime as dt
import json

import pytest

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.sync.codec import (
    LINKS, TABLES, IdMap, Unresolved, decode_link, decode_row, encode_link, encode_row,
)

NOW = dt.datetime(2026, 9, 22, 12, 0, tzinfo=dt.timezone.utc)


def _world(db):
    u = m.Utterance(text="lunch with Ali", source="text", captured_at=NOW)
    ali = m.Person(canonical_name="Ali", aliases=["Ally"], embedding=[0.1] * 768)
    place = m.Place(name="Arcadian", aliases=[])
    db.add_all([u, ali, place])
    db.flush()
    rec = m.Record(kind="task", title="call Ali", attributes={"k": [1, 2]},
                   due_at=NOW, source_utterance_id=u.id, assigned_by_person_id=ali.id,
                   embedding=[0.2] * 768)
    db.add(rec)
    db.flush()
    db.add(m.RecordPerson(record_id=rec.id, person_id=ali.id, role="with"))
    db.flush()
    return u, ali, place, rec


def test_registry_orders_parents_before_children():
    names = [t[0] for t in TABLES]
    assert names.index("people") < names.index("records") < names.index("collections")
    assert names.index("conversations") < names.index("messages")
    assert {l[0] for l in LINKS} == {"record_people", "record_places", "record_items",
                                      "record_occasions", "occasion_people"}


@requires_db
def test_record_round_trip_maps_foreign_keys_through_sync_ids(db):
    u, ali, _, rec = _world(db)
    ids = IdMap(db)
    payload = encode_row(ids, "records", rec)
    json.dumps(payload)                                    # JSON-safe
    assert payload["sync_id"] == rec.sync_id
    assert payload["data"]["assigned_by_person_id"] == ali.sync_id
    assert payload["data"]["source_utterance_id"] == u.sync_id
    assert "id" not in payload["data"] and "embedding" not in payload["data"]
    kwargs = decode_row(ids, "records", payload)
    assert kwargs["assigned_by_person_id"] == ali.id
    assert kwargs["source_utterance_id"] == u.id
    assert kwargs["due_at"] == NOW and kwargs["attributes"] == {"k": [1, 2]}


@requires_db
def test_unknown_parent_raises_unresolved(db):
    _, _, _, rec = _world(db)
    ids = IdMap(db)
    payload = encode_row(ids, "records", rec)
    payload["data"]["assigned_by_person_id"] = "00000000-0000-0000-0000-00000000dead"
    with pytest.raises(Unresolved) as e:
        decode_row(ids, "records", payload)
    assert e.value.sync_id.endswith("dead")


@requires_db
def test_alias_redirects_a_merged_away_id_to_the_survivor(db):
    _, ali, _, rec = _world(db)
    db.add(m.SyncAlias(alias="00000000-0000-0000-0000-00000000beef", canonical=ali.sync_id))
    db.flush()
    ids = IdMap(db)
    payload = encode_row(ids, "records", rec)
    payload["data"]["assigned_by_person_id"] = "00000000-0000-0000-0000-00000000beef"
    assert decode_row(ids, "records", payload)["assigned_by_person_id"] == ali.id


@requires_db
def test_date_and_array_columns_round_trip(db):
    occ = m.Occasion(name="Birthday", date=dt.date(2026, 10, 3))
    per = m.Person(canonical_name="Nafay", aliases=["Naf", "Nafi"], notes="friend")
    db.add_all([occ, per])
    db.flush()
    ids = IdMap(db)
    o = encode_row(ids, "occasions", occ)
    assert o["data"]["date"] == "2026-10-03"
    assert decode_row(ids, "occasions", o)["date"] == dt.date(2026, 10, 3)
    p = decode_row(ids, "people", encode_row(ids, "people", per))
    assert p["aliases"] == ["Naf", "Nafi"] and p["notes"] == "friend"


@requires_db
def test_link_round_trip(db):
    _, ali, _, rec = _world(db)
    ids = IdMap(db)
    link = db.get(m.RecordPerson, (rec.id, ali.id))
    payload = encode_link(ids, "record_people", link)
    assert payload["a"] == rec.sync_id and payload["b"] == ali.sync_id
    assert payload["role"] == "with"
    kwargs = decode_link(ids, "record_people", payload)
    assert kwargs == {"record_id": rec.id, "person_id": ali.id, "role": "with"}
