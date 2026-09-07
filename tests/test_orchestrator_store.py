import datetime as dt

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.models_domain import (
    ExtractionResult,
    ExtractedPerson,
    ExtractedPlace,
    ExtractedRecord,
)
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 7, 18, 0, tzinfo=dt.timezone.utc)


def _stub_embedder(monkeypatch):
    import io_assistant.orchestrator as orch

    monkeypatch.setattr(
        orch,
        "Embedder",
        lambda cfg: type(
            "E",
            (),
            {
                "embed_one": lambda self, t: [0.0] * 768,
                "embed": lambda self, ts: [[0.0] * 768 for _ in ts],
            },
        )(),
    )


@requires_db
def test_store_path_writes_record(db, engine, config, fake_backend, monkeypatch):
    fake_backend.set_intent("store")
    fake_backend.set_extraction(
        ExtractionResult(
            people=[ExtractedPerson(name="Nafay", confidence=0.95)],
            places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
            records=[
                ExtractedRecord(
                    kind="event",
                    domain="social",
                    title="dinner",
                    when_phrase="today",
                    people=["Nafay"],
                    places=["Arcadian"],
                    confidence=0.9,
                )
            ],
        )
    )
    _stub_embedder(monkeypatch)
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("I had dinner with Nafay at Arcadian", captured_at=NOW)
    assert res.intent == "store" and res.stored and len(res.stored.record_ids) == 1
    assert "Nafay" in res.message
    assert db.query(m.Record).count() == 1


@requires_db
def test_unknown_intent_message(db, config, fake_backend):
    fake_backend.set_intent("unknown")
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("asdfgh")
    assert res.intent == "unknown" and "rephrase" in res.message.lower()


@requires_db
def test_query_intent_message(db, config, fake_backend):
    fake_backend.set_intent("query")
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("what did I do yesterday?")
    assert res.intent == "query"
    assert res.stored is None
    assert "Plan 2" in res.message


@requires_db
def test_extraction_failure_marks_utterance(db, config, fake_backend, monkeypatch):
    fake_backend.set_intent("store")

    def boom(*a, **k):
        from io_assistant.backend.local import BackendParseError

        raise BackendParseError("nope")

    fake_backend.extract = boom
    _stub_embedder(monkeypatch)
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("something mumbled")
    assert res.stored is None
    assert (
        db.query(m.Utterance).filter_by(marker="extraction_failed").count() == 1
    )


@requires_db
def test_gated_low_confidence_message(db, config, fake_backend, monkeypatch):
    fake_backend.set_intent("store")
    fake_backend.set_extraction(
        ExtractionResult(
            records=[
                ExtractedRecord(
                    kind="note",
                    title="something vague",
                    confidence=0.2,
                )
            ],
        )
    )
    _stub_embedder(monkeypatch)
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("maybe something happened", captured_at=NOW)
    assert res.stored is not None and res.stored.gated is True
    assert res.stored.gate_reasons
    assert res.stored.gate_reasons[0] in res.message
    assert "yes" in res.message.lower()


@requires_db
def test_doctor_cli_smoke():
    from typer.testing import CliRunner
    from io_assistant.cli import app

    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "not implemented" in result.stdout
