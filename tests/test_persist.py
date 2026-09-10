import datetime as dt

import pytest

from tests.conftest import requires_db
from io_assistant.persist.writer import persist_store, PersistError
from io_assistant.resolve.resolver import EntityResolver
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedItem,
    ExtractedRecord, ExtractedOccasion)
from io_assistant.db import models as m


class StubEmbedder:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def embed_one(self, t):
        return self.mapping.get(t, [0.0] * 768)

    def embed(self, ts):
        return [self.embed_one(t) for t in ts]


NOW = dt.datetime(2026, 9, 7, 18, 0, tzinfo=dt.timezone.utc)


def _arcadian() -> ExtractionResult:
    return ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95),
                ExtractedPerson(name="Eelian", confidence=0.9)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        occasions=[ExtractedOccasion(name="Nafay and Eelian's birthday", date_phrase=None, confidence=0.8)],
        records=[ExtractedRecord(kind="event", domain="social",
                                 title="went out to eat", when_phrase="today",
                                 people=["Nafay", "Eelian"], places=["Arcadian"],
                                 occasions=["Nafay and Eelian's birthday"],
                                 attributes={"meal": "dinner"}, confidence=0.9)])


@requires_db
def test_persists_record_with_links(db, config):
    res = EntityResolver(db, StubEmbedder(), config.resolver)
    out = persist_store(db, StubEmbedder(), res,
        utterance_text="I went out with Nafay to eat at Arcadian for his and Eelian's birthday",
        source="text", captured_at=NOW, extraction=_arcadian(), now=NOW,
        confidence_gate=config.resolver.confidence_gate_threshold)
    assert not out.gated and len(out.record_ids) == 1
    rec = db.get(m.Record, out.record_ids[0])
    assert rec.kind == "event" and rec.attributes["meal"] == "dinner"
    assert rec.occurred_at.date() == dt.date(2026, 9, 7)
    assert db.query(m.RecordPerson).filter_by(record_id=rec.id).count() == 2
    assert db.query(m.RecordPlace).filter_by(record_id=rec.id).count() == 1
    assert db.query(m.RecordOccasion).filter_by(record_id=rec.id).count() == 1
    assert db.query(m.Person).filter(m.Person.canonical_name.in_(["Nafay", "Eelian"])).count() == 2
    assert len(out.new_entities) == 3


@requires_db
def test_arbitrary_kind_record(db, config):
    ext = ExtractionResult(records=[ExtractedRecord(
        kind="Gym Session", domain="fitness", title="leg day",
        body="squats 100kg", when_phrase="today", confidence=0.9)])
    out = persist_store(db, StubEmbedder(),
        EntityResolver(db, StubEmbedder(), config.resolver),
        utterance_text="did leg day, squats up to 100", source="text", captured_at=NOW,
        extraction=ext, now=NOW, confidence_gate=0.6)
    rec = db.get(m.Record, out.record_ids[0])
    assert rec.kind == "gym_session"
    assert rec.domain == "other"


@requires_db
def test_low_confidence_gates_and_keeps_only_utterance(db, config):
    ext = _arcadian()
    ext.records[0].confidence = 0.3
    out = persist_store(db, StubEmbedder(),
        EntityResolver(db, StubEmbedder(), config.resolver),
        utterance_text="mumble arcadian something", source="text", captured_at=NOW,
        extraction=ext, now=NOW, confidence_gate=0.6)
    assert out.gated and "low confidence" in " ".join(out.gate_reasons).lower()
    assert db.query(m.Record).count() == 0
    assert db.get(m.Utterance, out.utterance_id) is not None


@requires_db
def test_confirmed_bypasses_gate(db, config):
    ext = _arcadian()
    ext.records[0].confidence = 0.3
    out = persist_store(db, StubEmbedder(),
        EntityResolver(db, StubEmbedder(), config.resolver),
        utterance_text="x", source="text", captured_at=NOW, extraction=ext, now=NOW,
        confidence_gate=0.6, confirmed=True)
    assert not out.gated and len(out.record_ids) == 1


@requires_db
def test_ambiguous_entity_gates(db, config):
    db.add(m.Person(canonical_name="Jonathan", aliases=[], embedding=[1.0] + [0.0] * 767))
    db.flush()
    emb = StubEmbedder({"Jon": [1.0] + [0.0] * 767})
    ext = ExtractionResult(
        people=[ExtractedPerson(name="Jon", confidence=0.95)],
        records=[ExtractedRecord(kind="note", domain="social", title="saw Jon",
                                 when_phrase="today", people=["Jon"], confidence=0.9)])
    out = persist_store(db, emb, EntityResolver(db, emb, config.resolver),
        utterance_text="ran into Jon", source="text", captured_at=NOW,
        extraction=ext, now=NOW, confidence_gate=0.6)
    assert out.gated and "ambiguous" in " ".join(out.gate_reasons).lower()
    assert db.query(m.Record).count() == 0


class FailingEmbedder:
    """Succeeds on the first embed_one call, raises on the second."""

    def __init__(self):
        self.calls = 0

    def embed_one(self, t):
        self.calls += 1
        if self.calls >= 2:
            raise RuntimeError("boom")
        return [0.0] * 768

    def embed(self, ts):
        return [self.embed_one(t) for t in ts]


@requires_db
def test_write_failure_keeps_only_utterance_and_raises(db, config):
    text = "I went out with Nafay to eat at Arcadian for his and Eelian's birthday"
    res = EntityResolver(db, StubEmbedder(), config.resolver)
    with pytest.raises(PersistError):
        persist_store(db, FailingEmbedder(), res,
            utterance_text=text, source="text", captured_at=NOW,
            extraction=_arcadian(), now=NOW,
            confidence_gate=config.resolver.confidence_gate_threshold)
    assert db.query(m.Record).count() == 0
    assert db.query(m.Person).filter(
        m.Person.canonical_name.in_(["Nafay", "Eelian"])).count() == 0
    assert db.query(m.Utterance).filter_by(text=text).count() == 1


@requires_db
def test_ambiguous_entity_confirmed_uses_candidate(db, config):
    """Confirming an ambiguity gate means 'yes, that candidate' — it must
    accept the suggestion, not create the duplicate the gate prevents."""
    jonathan = m.Person(canonical_name="Jonathan", aliases=[],
                        embedding=[1.0] + [0.0] * 767)
    db.add(jonathan)
    db.flush()
    emb = StubEmbedder({"Jon": [1.0] + [0.0] * 767})
    ext = ExtractionResult(
        people=[ExtractedPerson(name="Jon", confidence=0.95)],
        records=[ExtractedRecord(kind="note", domain="social", title="saw Jon",
                                 when_phrase="today", people=["Jon"], confidence=0.9)])
    out = persist_store(db, emb, EntityResolver(db, emb, config.resolver),
        utterance_text="ran into Jon", source="text", captured_at=NOW,
        extraction=ext, now=NOW, confidence_gate=0.6, confirmed=True)
    assert not out.gated and len(out.record_ids) == 1
    assert out.new_entities == []
    assert db.query(m.Person).filter_by(canonical_name="Jon").count() == 0
    links = db.query(m.RecordPerson).filter_by(record_id=out.record_ids[0]).all()
    assert [l.person_id for l in links] == [jonathan.id]


@requires_db
def test_repeated_name_in_extraction_creates_one_entity(db, config):
    """A name repeated (in any casing) within one extraction must resolve and
    create exactly once — no orphaned duplicate rows."""
    ext = ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.9),
                ExtractedPerson(name="Nafay", confidence=0.9),
                ExtractedPerson(name="nafay", confidence=0.9)],
        records=[ExtractedRecord(kind="note", domain="social", title="saw Nafay",
                                 when_phrase="today", people=["Nafay"],
                                 confidence=0.9)])
    out = persist_store(db, StubEmbedder(),
        EntityResolver(db, StubEmbedder(), config.resolver),
        utterance_text="ran into Nafay", source="text", captured_at=NOW,
        extraction=ext, now=NOW, confidence_gate=0.6)
    assert not out.gated and len(out.record_ids) == 1
    assert db.query(m.Person).filter_by(canonical_name="Nafay").count() == 1
    assert db.query(m.Person).count() == 1
    assert out.new_entities == [("person", "Nafay")]
    assert db.query(m.RecordPerson).filter_by(record_id=out.record_ids[0]).count() == 1


@requires_db
def test_record_only_person_still_links(db, config):
    """A person named only inside rec.people (not the top-level people[]) must
    still be resolved and linked, not silently dropped."""
    ext = ExtractionResult(records=[ExtractedRecord(
        kind="event", title="lunch", when_phrase="today",
        people=["Sana"], confidence=0.9)])
    out = persist_store(db, StubEmbedder(),
        EntityResolver(db, StubEmbedder(), config.resolver),
        utterance_text="lunch with Sana", source="text", captured_at=NOW,
        extraction=ext, now=NOW, confidence_gate=0.6)
    rid = out.record_ids[0]
    assert db.query(m.RecordPerson).filter_by(record_id=rid).count() == 1
    assert db.query(m.Person).filter_by(canonical_name="Sana").count() == 1


@requires_db
def test_record_item_link_persists(db, config):
    ext = ExtractionResult(
        items=[ExtractedItem(name="drill", aliases=[], confidence=0.9)],
        records=[ExtractedRecord(kind="task", title="return the drill",
                                 items=["drill"], confidence=0.9)])
    out = persist_store(db, StubEmbedder(),
        EntityResolver(db, StubEmbedder(), config.resolver),
        utterance_text="return the drill", source="text", captured_at=NOW,
        extraction=ext, now=NOW, confidence_gate=0.6)
    rid = out.record_ids[0]
    assert db.query(m.RecordItem).filter_by(record_id=rid).count() == 1


def _persist_rec(db, config, rec):
    return persist_store(
        db, StubEmbedder(),
        EntityResolver(db, StubEmbedder(), config.resolver),
        utterance_text="x", source="text", captured_at=NOW,
        extraction=ExtractionResult(records=[rec]), now=NOW,
        confidence_gate=config.resolver.confidence_gate_threshold)


@requires_db
def test_bare_task_defaults_to_due_today(db, config):
    from io_assistant.resolve.dates import start_of_day
    out = _persist_rec(db, config, ExtractedRecord(
        kind="task", title="call the dentist", confidence=0.9))
    assert not out.gated
    rec = db.get(m.Record, out.record_ids[0])
    assert rec.due_at == start_of_day(NOW)
    assert rec.occurred_at is None
    assert rec.status == "open"


@requires_db
def test_someday_task_stays_dateless(db, config):
    out = _persist_rec(db, config, ExtractedRecord(
        kind="task", title="learn the cello", when_phrase="someday",
        confidence=0.9))
    assert not out.gated
    rec = db.get(m.Record, out.record_ids[0])
    assert rec.due_at is None


@requires_db
def test_non_task_kind_is_never_defaulted(db, config):
    out = _persist_rec(db, config, ExtractedRecord(
        kind="gym_session", title="leg day", confidence=0.9))
    rec = db.get(m.Record, out.record_ids[0])
    assert rec.due_at is None and rec.occurred_at is None


@requires_db
def test_recurring_chore_is_not_defaulted_to_due_today(db, config):
    out = _persist_rec(db, config, ExtractedRecord(
        kind="chore", title="take out the trash",
        recurrence_phrase="every Monday", confidence=0.9))
    rec = db.get(m.Record, out.record_ids[0])
    assert rec.due_at is None
    assert rec.recurrence_rule == "FREQ=WEEKLY;BYDAY=MO"


@requires_db
def test_task_with_explicit_due_phrase_keeps_it(db, config):
    from io_assistant.resolve.dates import start_of_day
    out = _persist_rec(db, config, ExtractedRecord(
        kind="task", title="file taxes", due_phrase="tomorrow", confidence=0.9))
    rec = db.get(m.Record, out.record_ids[0])
    assert rec.due_at is not None and rec.due_at != start_of_day(NOW)


@requires_db
def test_unreadable_recurrence_gates(db, config):
    ext = ExtractionResult(records=[ExtractedRecord(
        kind="chore", title="water plants",
        recurrence_phrase="whenever the soil looks dry", confidence=0.9)])
    out = persist_store(db, StubEmbedder(),
        EntityResolver(db, StubEmbedder(), config.resolver),
        utterance_text="water the plants when dry", source="text", captured_at=NOW,
        extraction=ext, now=NOW, confidence_gate=0.6)
    assert out.gated is True
    assert any("repeat rule" in r for r in out.gate_reasons)
