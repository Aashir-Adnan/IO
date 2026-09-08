import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.extract.acknowledge import build_fact_list
from io_assistant.models_domain import ExtractionResult, ExtractedRecord

NOW = dt.datetime(2026, 9, 8, 20, 0, tzinfo=dt.timezone.utc)


@requires_db
def test_build_fact_list_from_written_rows(db):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    p = m.Person(canonical_name="Nafay", aliases=[])
    db.add(p)
    db.flush()
    r = m.Record(kind="event", domain="social", title="dinner with Nafay",
                 occurred_at=NOW, attributes={}, source_utterance_id=u.id)
    db.add(r)
    db.flush()
    db.add(m.RecordPerson(record_id=r.id, person_id=p.id))
    db.flush()

    class PR:
        record_ids = [r.id]

    out = build_fact_list(db, PR(), ExtractionResult(records=[
        ExtractedRecord(kind="event", title="dinner with Nafay", confidence=0.9)]), NOW)
    assert 'event "dinner with Nafay"' in out
    assert "Nafay" in out and "2026-09-08" in out


def test_fake_backend_records_context(fake_backend):
    fake_backend.set_intent("query")
    fake_backend.route("and last week?",
                       context="you: where did I see Nafay\nio: Tuesday")
    assert "Nafay" in fake_backend.last_context


def test_fake_backend_acknowledge(fake_backend):
    fake_backend.set_ack("Logged dinner with Nafay at Arcadian.")
    assert fake_backend.acknowledge('event "dinner"; with Nafay') == "Logged dinner with Nafay at Arcadian."
