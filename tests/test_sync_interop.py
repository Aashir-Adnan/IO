"""Cross-language sync conformance: the Python engine and the phone's Dart
engine must read each other's files. Fixtures are committed under
phone/test/fixtures/sync/{python,dart}/ — each side verifies it can consume the
other's. Regenerate (only when the wire format changes on purpose):

    IO_REGEN_FIXTURES=1 uv run pytest tests/test_sync_interop.py -k regen   # python/
    IO_REGEN_FIXTURES=1 flutter test test/sync/interop_test.dart            # dart/  (from phone/)
"""
import datetime as dt
import os
import shutil
from pathlib import Path

import pytest

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.sync.engine import SyncEngine
from io_assistant.sync.stores import FolderStore

FIX = Path(__file__).resolve().parents[1] / "phone" / "test" / "fixtures" / "sync"
T0 = dt.datetime(2026, 9, 1, 9, 0, tzinfo=dt.timezone.utc)

U, P, PL, R, O, C, MSG = (f"00000000-0000-4000-8000-00000000000{i}" for i in range(1, 8))


def seed(sf):
    """The shared scenario — the Dart side seeds exactly the same rows."""
    with sf() as s:
        u = m.Utterance(sync_id=U, text="call Nafay about dinner", source="text",
                        captured_at=T0, updated_at=T0)
        p = m.Person(sync_id=P, canonical_name="Nafay", aliases=["naf"], notes="friend",
                     created_at=T0, updated_at=T0)
        pl = m.Place(sync_id=PL, name="Arcadian", type="restaurant", aliases=[],
                     created_at=T0, updated_at=T0)
        o = m.Occasion(sync_id=O, name="Eid", date=dt.date(2026, 10, 3), created_at=T0, updated_at=T0)
        c = m.Conversation(sync_id=C, title="hello", started_at=T0, last_at=T0, updated_at=T0)
        s.add_all([u, p, pl, o, c])
        s.flush()
        r = m.Record(sync_id=R, kind="task", title="call Nafay", status="open",
                     due_at=dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc),
                     attributes={"meal": "dinner", "n": 2}, assigned_by_person_id=p.id,
                     source_utterance_id=u.id, created_at=T0, updated_at=T0)
        s.add_all([r, m.Message(sync_id=MSG, conversation_id=c.id, role="user", text="hi ✓",
                                source="text", created_at=T0, updated_at=T0)])
        s.flush()
        s.add_all([m.RecordPerson(record_id=r.id, person_id=p.id, role="with"),
                   m.RecordPlace(record_id=r.id, place_id=pl.id),
                   m.RecordOccasion(record_id=r.id, occasion_id=o.id)])
        s.commit()


def check_state(sf):
    """What a device must look like after pulling the scenario."""
    with sf() as s:
        p = s.query(m.Person).one()
        assert (p.sync_id, p.canonical_name, p.aliases, p.notes) == (P, "Nafay", ["naf"], "friend")
        r = s.query(m.Record).one()
        assert r.sync_id == R and r.kind == "task" and r.status == "open"
        assert r.attributes == {"meal": "dinner", "n": 2}
        assert r.due_at == dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc)
        assert r.assigned_by_person_id == p.id
        assert s.get(m.Utterance, r.source_utterance_id).sync_id == U
        assert s.query(m.Place).one().type == "restaurant"
        assert s.query(m.Occasion).one().date == dt.date(2026, 10, 3)
        assert s.query(m.RecordPerson).one().role == "with"
        assert s.query(m.RecordPlace).count() == 1 and s.query(m.RecordOccasion).count() == 1
        msg = s.query(m.Message).one()
        assert msg.text == "hi ✓"
        assert s.get(m.Conversation, msg.conversation_id).title == "hello"


@pytest.mark.skipif(os.environ.get("IO_REGEN_FIXTURES") != "1", reason="fixture regeneration")
@requires_db
def test_regen_python_fixture(devices):
    out = FIX / "python"
    shutil.rmtree(out, ignore_errors=True)
    seed(devices["a"])
    SyncEngine(devices["a"], FolderStore(out), "PY").push()


@requires_db
def test_python_engine_consumes_the_dart_fixture(devices, tmp_path):
    src = FIX / "dart"
    assert src.exists(), "missing Dart fixture: run the regen command in this file's docstring"
    shutil.copytree(src, tmp_path / "store")
    eng = SyncEngine(devices["b"], FolderStore(tmp_path / "store"), "PYB")
    assert eng.pull() > 0 and eng.last_error is None
    check_state(devices["b"])


@requires_db
def test_python_fixture_round_trips_through_python_too(devices, tmp_path):
    """Guards the fixture itself: what Python wrote is what Python reads."""
    src = FIX / "python"
    assert src.exists(), "missing Python fixture: run the regen command in this file's docstring"
    shutil.copytree(src, tmp_path / "store")
    eng = SyncEngine(devices["c"], FolderStore(tmp_path / "store"), "PYC")
    assert eng.pull() > 0
    check_state(devices["c"])
