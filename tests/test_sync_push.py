import datetime as dt
import gzip
import json

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.sync.engine import SyncEngine
from io_assistant.sync.stores import FolderStore

NOW = dt.datetime(2026, 9, 22, 12, 0, tzinfo=dt.timezone.utc)


def seed(sf, name="Ali"):
    """utterance + person + record + affiliation (4 syncable rows)."""
    with sf() as s:
        u = m.Utterance(text=f"met {name}", source="text", captured_at=NOW)
        p = m.Person(canonical_name=name, aliases=[])
        s.add_all([u, p])
        s.flush()
        r = m.Record(kind="event", title=f"met {name}", attributes={},
                     source_utterance_id=u.id)
        s.add(r)
        s.flush()
        s.add(m.RecordPerson(record_id=r.id, person_id=p.id))
        s.commit()


def batches(root, dev="A"):
    files = sorted((root / f"dev-{dev}").glob("batch-*.json.gz"))
    return [json.loads(gzip.decompress(f.read_bytes())) for f in files]


def engine(devices, key, root, dev):
    return SyncEngine(devices[key], FolderStore(root), dev)


def test_folder_store_round_trip(tmp_path):
    st = FolderStore(tmp_path)
    st.put("dev-A/batch-00000001.json.gz", b"x")
    st.put("dev-B/snapshot-00000002.json.gz", b"y")
    assert st.list("dev-") == ["dev-A/batch-00000001.json.gz", "dev-B/snapshot-00000002.json.gz"]
    assert st.list("dev-A/") == ["dev-A/batch-00000001.json.gz"]
    assert st.get("dev-A/batch-00000001.json.gz") == b"x"
    st.delete("dev-A/batch-00000001.json.gz")
    assert st.list("dev-A/") == []


@requires_db
def test_push_writes_one_batch_for_dirty_rows(devices, tmp_path):
    seed(devices["a"])
    eng = engine(devices, "a", tmp_path, "A")
    assert eng.push() == 4
    (b,) = batches(tmp_path)
    kinds = [i["k"] for i in b["items"]]
    assert kinds.count("row") == 3 and kinds.count("link") == 1
    assert b["device"] == "A" and b["seq"] == 1
    assert eng.push() == 0
    assert len(batches(tmp_path)) == 1          # nothing new, nothing written


@requires_db
def test_pushed_rows_are_marked_clean(devices, tmp_path):
    seed(devices["a"])
    engine(devices, "a", tmp_path, "A").push()
    with devices["a"]() as s:
        p = s.query(m.Person).one()
        assert p.synced_at is not None and p.synced_at == p.updated_at
        assert s.query(m.RecordPerson).one().synced_at is not None


@requires_db
def test_edit_pushes_only_that_row(devices, tmp_path):
    seed(devices["a"])
    eng = engine(devices, "a", tmp_path, "A")
    eng.push()
    with devices["a"]() as s:
        s.query(m.Person).one().notes = "friend from work"
        s.commit()
    assert eng.push() == 1
    b = batches(tmp_path)[1]
    assert b["seq"] == 2
    (item,) = b["items"]
    assert item["t"] == "people" and item["data"]["notes"] == "friend from work"


@requires_db
def test_delete_pushes_a_tombstone_once(devices, tmp_path):
    seed(devices["a"])
    eng = engine(devices, "a", tmp_path, "A")
    eng.push()
    with devices["a"]() as s:
        rec = s.query(m.Record).one()
        sid = rec.sync_id
        s.delete(rec)
        s.commit()
    assert eng.push() == 1
    (item,) = batches(tmp_path)[1]["items"]
    assert item["k"] == "tomb" and item["t"] == "records" and item["sync_id"] == sid
    assert eng.push() == 0


@requires_db
def test_row_edited_while_pushing_stays_dirty(devices, tmp_path):
    seed(devices["a"])

    class RacyStore(FolderStore):
        def put(self, path, data):
            super().put(path, data)
            with devices["a"]() as s:          # a local edit lands mid-push
                s.query(m.Person).one().notes = "edited during push"
                s.commit()

    eng = SyncEngine(devices["a"], RacyStore(tmp_path), "A")
    eng.push()
    assert eng.push() == 1                       # the racing edit is still dirty


@requires_db
def test_large_pushes_are_chunked_into_sequential_batches(devices, tmp_path, monkeypatch):
    import io_assistant.sync.engine as eng_mod
    monkeypatch.setattr(eng_mod, "CHUNK", 2)
    seed(devices["a"])
    assert engine(devices, "a", tmp_path, "A").push() == 4
    assert [b["seq"] for b in batches(tmp_path)] == [1, 2]
