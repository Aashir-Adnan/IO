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
def test_query_intent_answers(db, config, fake_backend, monkeypatch):
    import io_assistant.orchestrator as orch

    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())
    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [], "answer_shape": "text"})
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("what did I do yesterday?")
    assert res.intent == "query"
    assert res.stored is None
    # nothing stored yet -> deterministic empty answer, model not called
    assert "anything" in res.message.lower()
    assert db.query(m.Utterance).filter_by(resolved_intent="query").count() == 1


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
def test_write_failure_keeps_utterance_and_does_not_raise(
    db, config, fake_backend, monkeypatch
):
    """A failed write pass must never take the verbatim utterance with it:
    handle() returns a message instead of raising, so the CLI still commits."""
    fake_backend.set_intent("store")
    fake_backend.set_extraction(
        ExtractionResult(
            people=[ExtractedPerson(name="Nafay", confidence=0.95)],
            records=[
                ExtractedRecord(
                    kind="event",
                    domain="social",
                    title="dinner",
                    when_phrase="today",
                    people=["Nafay"],
                    confidence=0.9,
                )
            ],
        )
    )

    class FailingEmbedder:
        def __init__(self):
            self.calls = 0

        def embed_one(self, t):
            self.calls += 1
            if self.calls >= 2:
                raise RuntimeError("boom")
            return [0.0] * 768

        def embed(self, ts):
            return [self.embed_one(t) for t in ts]

    import io_assistant.orchestrator as orch

    monkeypatch.setattr(orch, "Embedder", lambda cfg: FailingEmbedder())
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    text = "I had dinner with Nafay"
    res = o.handle(text, captured_at=NOW)  # must NOT raise
    assert res.intent == "store" and res.stored is None
    assert "kept a note" in res.message
    assert db.query(m.Record).count() == 0
    assert db.query(m.Utterance).filter_by(text=text).count() == 1


@requires_db
def test_handle_commits_utterance_even_when_write_fails(
    db, config, fake_backend, monkeypatch
):
    """handle() owns the session: after a failed write pass it still commits the
    verbatim utterance. A second session on the same connection (i.e. not the
    Orchestrator's, which handle() has already closed) sees the row."""
    from sqlalchemy.orm import sessionmaker

    fake_backend.set_intent("store")
    fake_backend.set_extraction(
        ExtractionResult(
            records=[
                ExtractedRecord(
                    kind="event", title="doomed", when_phrase="today",
                    confidence=0.9,
                )
            ]
        )
    )

    class HalfEmbedder:
        def embed_one(self, t):
            if "doomed" in t:
                raise RuntimeError("embedding backend down")
            return [0.0] * 768

        def embed(self, ts):
            return [[0.0] * 768 for _ in ts]

    import io_assistant.orchestrator as orch

    monkeypatch.setattr(orch, "Embedder", lambda cfg: HalfEmbedder())

    factory = sessionmaker(bind=db.connection(), future=True, expire_on_commit=False)
    o = Orchestrator(config, session_factory=factory, backend=fake_backend)
    text = "a sentence that will not store"
    res = o.handle(text, captured_at=NOW)
    assert res.stored is None and "kept a note" in res.message

    check = factory()
    try:
        rows = check.query(m.Utterance).filter_by(text=text).all()
        assert len(rows) == 1 and rows[0].resolved_intent == "store"
        assert check.query(m.Record).filter_by(title="doomed").count() == 0
    finally:
        check.close()


@requires_db
def test_confirm_replays_without_reextraction(db, config, fake_backend, monkeypatch):
    """Confirming a gated store replays the held extraction: no re-route, no
    re-extract, and no second utterance row."""
    fake_backend.set_intent("store")
    first = ExtractionResult(
        records=[ExtractedRecord(kind="note", title="original title", confidence=0.2)]
    )
    fake_backend.set_extraction(first)
    _stub_embedder(monkeypatch)
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)

    res = o.handle("maybe something happened", captured_at=NOW)
    assert res.stored is not None and res.stored.gated is True
    assert res.pending is not None
    assert db.query(m.Utterance).count() == 1

    # The model would now answer differently — the replay must ignore it.
    fake_backend.set_extraction(
        ExtractionResult(
            records=[ExtractedRecord(kind="note", title="DIFFERENT", confidence=0.9)]
        )
    )
    calls_before = list(fake_backend.calls)

    res2 = o.handle(res.pending.text, pending=res.pending)
    assert res2.stored is not None and not res2.stored.gated
    assert len(res2.stored.record_ids) == 1
    rec = db.get(m.Record, res2.stored.record_ids[0])
    assert rec.title == "original title"
    assert rec.source_utterance_id == res.pending.utterance_id
    assert db.query(m.Utterance).count() == 1
    assert fake_backend.calls == calls_before  # no route, no extract


def test_doctor_cli_smoke(monkeypatch):
    from typer.testing import CliRunner
    import io_assistant.cli as cli
    import io_assistant.doctor as d

    monkeypatch.setattr(cli, "load_config", lambda: object())
    monkeypatch.setattr(
        d, "run_checks", lambda c: [d.Check("PostgreSQL", True, "ok")]
    )
    result = CliRunner().invoke(cli.app, ["doctor"])
    assert result.exit_code == 0
    assert "OK" in result.stdout and "PostgreSQL" in result.stdout
