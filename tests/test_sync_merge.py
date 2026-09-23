import datetime as dt
import gzip
import json
import uuid

import pytest

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.sync.engine import SyncEngine
from io_assistant.sync.stores import FolderStore

T0 = dt.datetime(2026, 9, 1, 9, 0, tzinfo=dt.timezone.utc)   # safely in the past (the engine clamps future timestamps)
MIN = dt.timedelta(minutes=1)


def pair(devices, tmp_path, keys="ab"):
    store = FolderStore(tmp_path)
    return [SyncEngine(devices[k], store, k.upper()) for k in keys]


def converge(*engines, rounds=3):
    for _ in range(rounds):
        for e in engines:
            e.sync()


def seed_friend(sf, name="Ali", title=None, created=T0):
    with sf() as s:
        u = m.Utterance(text=f"met {name}", source="text", captured_at=T0)
        p = m.Person(canonical_name=name, aliases=[], created_at=created, updated_at=created)
        s.add_all([u, p])
        s.flush()
        r = m.Record(kind="event", title=title or f"met {name}", attributes={},
                     source_utterance_id=u.id, created_at=created, updated_at=created)
        s.add(r)
        s.flush()
        s.add(m.RecordPerson(record_id=r.id, person_id=p.id))
        s.commit()


def people(sf):
    with sf() as s:
        return s.query(m.Person).order_by(m.Person.id).all()


@requires_db
def test_a_friend_told_to_one_device_appears_on_the_other(devices, tmp_path):
    a, b = pair(devices, tmp_path)
    seed_friend(devices["a"], "Ali")
    a.push()
    assert b.pull() == 4
    with devices["b"]() as s:
        p = s.query(m.Person).one()
        r = s.query(m.Record).one()
        link = s.query(m.RecordPerson).one()
        assert p.canonical_name == "Ali" and r.title == "met Ali"
        assert (link.record_id, link.person_id) == (r.id, p.id)
        assert p.embedding is None                         # vectors are never synced
    with devices["a"]() as sa:
        assert sa.query(m.Person).one().sync_id == p.sync_id


@requires_db
@pytest.mark.parametrize("newer", ["a", "b"])
def test_the_newer_edit_wins_in_either_direction(devices, tmp_path, newer):
    a, b = pair(devices, tmp_path)
    seed_friend(devices["a"])
    converge(a, b)
    for key, stamp, note in (("a", T0 + (2 if newer == "a" else 1) * MIN, "from A"),
                             ("b", T0 + (2 if newer == "b" else 1) * MIN, "from B")):
        with devices[key]() as s:
            p = s.query(m.Person).one()
            p.notes, p.updated_at = note, stamp
            s.commit()
    converge(a, b)
    want = "from A" if newer == "a" else "from B"
    assert [p.notes for p in people(devices["a"])] == [want]
    assert [p.notes for p in people(devices["b"])] == [want]


@requires_db
def test_deletes_propagate_and_are_not_resurrected_by_a_replay(devices, tmp_path):
    a, b = pair(devices, tmp_path)
    seed_friend(devices["a"])
    converge(a, b)
    with devices["a"]() as s:
        s.delete(s.query(m.Record).one())
        s.commit()
    converge(a, b)
    with devices["b"]() as s:
        assert s.query(m.Record).count() == 0
        assert s.query(m.RecordPerson).count() == 0        # link cascaded
        assert s.query(m.Person).count() == 1
    # replay A's very first batch on B: the record must stay deleted
    with devices["b"]() as s:
        s.get(m.SyncState, "applied:A").value = {"v": 0}
        s.commit()
    b.pull()
    with devices["b"]() as s:
        assert s.query(m.Record).count() == 0


@requires_db
def test_a_completed_task_stays_done(devices, tmp_path):
    a, b = pair(devices, tmp_path)
    with devices["a"]() as s:
        u = m.Utterance(text="t", source="text", captured_at=T0)
        s.add(u)
        s.flush()
        s.add(m.Record(kind="task", title="pay rent", status="open", attributes={},
                       source_utterance_id=u.id, created_at=T0, updated_at=T0))
        s.commit()
    converge(a, b)
    with devices["b"]() as s:                      # B completes it (older edit)
        r = s.query(m.Record).one()
        r.status, r.completed_at, r.updated_at = "done", T0 + MIN, T0 + MIN
        s.commit()
    with devices["a"]() as s:                      # A retitles it later, still "open"
        r = s.query(m.Record).one()
        r.title, r.updated_at = "pay rent (March)", T0 + 5 * MIN
        s.commit()
    converge(a, b)
    for key in "ab":
        with devices[key]() as s:
            r = s.query(m.Record).one()
            assert (r.status, r.title) == ("done", "pay rent (March)")


@requires_db
def test_independent_duplicate_friends_collapse_to_one(devices, tmp_path):
    a, b = pair(devices, tmp_path)
    seed_friend(devices["a"], "Nafay", title="lunch with Nafay", created=T0)
    seed_friend(devices["b"], "Nafay", title="dinner with Nafay", created=T0 + 60 * MIN)
    a_sid = people(devices["a"])[0].sync_id
    converge(a, b, rounds=4)
    for key in "ab":
        with devices[key]() as s:
            (p,) = s.query(m.Person).all()             # exactly one Nafay
            assert p.sync_id == a_sid                  # the earlier-created one won
            titles = sorted(r.title for r in s.query(m.Record).all())
            assert titles == ["dinner with Nafay", "lunch with Nafay"]
            assert s.query(m.RecordPerson).count() == 2   # both records point at him


@requires_db
def test_dissimilar_names_are_not_merged(devices, tmp_path):
    a, b = pair(devices, tmp_path)
    seed_friend(devices["a"], "Hamza")
    seed_friend(devices["b"], "Hunza")
    converge(a, b)
    for key in "ab":
        assert sorted(p.canonical_name for p in people(devices[key])) == ["Hamza", "Hunza"]


@requires_db
def test_nothing_echoes_after_a_full_round(devices, tmp_path):
    a, b = pair(devices, tmp_path)
    seed_friend(devices["a"])
    converge(a, b)
    assert a.push() == 0 and b.push() == 0


def _write_batch(root, dev, seq, items):
    d = root / f"dev-{dev}"
    d.mkdir(parents=True, exist_ok=True)
    payload = {"v": 1, "device": dev, "seq": seq, "items": items}
    (d / f"batch-{seq:08d}.json.gz").write_bytes(gzip.compress(json.dumps(payload).encode()))


def _person(sid, name, upd=T0, created=T0):
    return {"k": "row", "t": "people", "sync_id": sid, "updated_at": upd.isoformat(),
            "data": {"canonical_name": name, "aliases": [], "notes": None,
                     "created_at": created.isoformat()}}


@requires_db
def test_an_unresolved_reference_waits_for_its_parent(devices, tmp_path):
    (a,) = pair(devices, tmp_path, "a")
    o, p = str(uuid.uuid4()), str(uuid.uuid4())
    # device X (listed first) has only the link; device Y has the rows it needs
    _write_batch(tmp_path, "X", 1, [{"k": "link", "t": "occasion_people",
                                     "a": o, "b": p, "role": None}])
    _write_batch(tmp_path, "Y", 1, [
        {"k": "row", "t": "occasions", "sync_id": o, "updated_at": T0.isoformat(),
         "data": {"name": "Eid", "date": None, "recurrence_rule": None,
                  "created_at": T0.isoformat()}},
        _person(p, "Zed")])
    a.pull()
    assert a.last_error and "waiting" in a.last_error
    with devices["a"]() as s:
        assert s.query(m.Person).count() == 1 and s.query(m.OccasionPerson).count() == 0
    a.pull()
    assert a.last_error is None
    with devices["a"]() as s:
        assert s.query(m.OccasionPerson).count() == 1


@requires_db
def test_future_timestamps_are_clamped(devices, tmp_path):
    now = T0 + 10 * MIN
    a = SyncEngine(devices["a"], FolderStore(tmp_path), "A", clock=lambda: now.timestamp())
    _write_batch(tmp_path, "X", 1, [_person(str(uuid.uuid4()), "Marty",
                                            upd=now + dt.timedelta(days=1))])
    a.pull()
    (p,) = people(devices["a"])
    assert p.updated_at <= now + 6 * MIN


@requires_db
def test_snapshot_compacts_and_bootstraps_a_new_device(devices, tmp_path, monkeypatch):
    import io_assistant.sync.engine as eng_mod
    monkeypatch.setattr(eng_mod, "SNAPSHOT_EVERY", 2)
    a, c = pair(devices, tmp_path, "ac")
    seed_friend(devices["a"], "Ali")
    a.push()
    for note in ("one", "two"):
        with devices["a"]() as s:
            s.query(m.Person).one().notes = note
            s.commit()
        a.push()
    a.sync()                                            # 3 batches -> snapshot + compact
    files = FolderStore(tmp_path).list("dev-A/")
    assert files == ["dev-A/snapshot-00000003.json.gz"]
    c.pull()
    with devices["c"]() as s:
        assert s.query(m.Person).one().notes == "two"
        assert s.query(m.Record).count() == 1 and s.query(m.RecordPerson).count() == 1
