"""Conversational task completion: the regex pre-check, the deterministic
close, the which-one gate, and the `complete_record` capability."""
import datetime as dt

import pytest

from io_assistant.db import models as m
from io_assistant.models_domain import (
    ExtractedRecord, ExtractionResult, Plan, Step,
)
from io_assistant.orchestrator import Orchestrator
from tests.conftest import requires_db

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def _stub_embedder(monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())


def _orch(config, db, fake_backend):
    return Orchestrator(config, session_factory=lambda: db, backend=fake_backend)


def _open_task(db, title):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    r = m.Record(kind="task", title=title, status="open", source_utterance_id=u.id)
    db.add(r); db.flush()
    return r.id


def _get(db, rid):
    """Re-read a record: Orchestrator.handle() closes the session it was
    handed, so instances from before the call are expunged."""
    return db.query(m.Record).filter_by(id=rid).one()


# --- the behavioural contract the pre-check regexes must satisfy ------------

@pytest.mark.parametrize("text,expected", [
    ("I finished the expense report", "done"),
    ("crossed the plants off", "done"),
    ("mark the dentist thing done", "done"),
    ("that's done", "done"),
    ("cancel the dentist task", "dropped"),
    ("forget the milk", "dropped"),
    ("I need to buy groceries", None),
    ("did I finish the report?", None),
    ("have I finished the report", None),
    ("what did I finish today?", None),
    ("remind me to water the plants", None),
    ("", None),
])
def test_complete_precheck_contract(config, fake_backend, text, expected):
    o = Orchestrator(config, session_factory=lambda: None, backend=fake_backend)
    assert o._complete_precheck(text) == expected


@requires_db
def test_finishing_a_task_closes_it_without_a_duplicate(config, db, fake_backend):
    rid = _open_task(db, "submit the expense report")
    before = db.query(m.Record).count()

    res = _orch(config, db, fake_backend).handle(
        "I finished the expense report", captured_at=NOW)

    r = _get(db, rid)
    assert r.status == "done" and r.completed_at is not None
    assert db.query(m.Record).count() == before   # no new record
    assert res.intent_kind == "ack"
    assert "plan" not in fake_backend.calls and "decide" not in fake_backend.calls


@requires_db
def test_cancelling_a_task_drops_it(config, db, fake_backend):
    rid = _open_task(db, "call the dentist")
    res = _orch(config, db, fake_backend).handle(
        "cancel the dentist task", captured_at=NOW)
    assert _get(db, rid).status == "dropped" and res.intent_kind == "ack"


@requires_db
def test_completion_with_nothing_open_acks_instead_of_storing(config, db, fake_backend):
    before = db.query(m.Record).count()
    res = _orch(config, db, fake_backend).handle(
        "I finished the laundry", captured_at=NOW)
    assert res.intent_kind == "ack"
    assert db.query(m.Record).count() == before   # no duplicate record


@requires_db
def test_i_need_to_still_stores_a_new_open_task(config, db, fake_backend):
    config.backend.decide = "combined"
    fake_backend.set_decide(Plan(steps=[Step(kind="store", extraction=ExtractionResult(
        records=[ExtractedRecord(kind="task", title="buy groceries",
                                 status="open", confidence=0.9)]))]))
    _orch(config, db, fake_backend).handle("I need to buy groceries", captured_at=NOW)
    assert db.query(m.Record).filter_by(title="buy groceries", status="open").count() == 1


@requires_db
def test_ambiguous_completion_gates_then_reply_closes_the_pick(config, db, fake_backend):
    a = _open_task(db, "call the dentist")
    b = _open_task(db, "book the dentist follow-up")
    o = _orch(config, db, fake_backend)

    gate = o.handle("mark the dentist thing done", captured_at=NOW)
    assert gate.intent_kind == "gate" and gate.pending is not None

    reply = o.handle("the first one", captured_at=NOW, pending=gate.pending)
    assert _get(db, a).status == "done" and _get(db, b).status == "open"
    assert reply.intent_kind == "ack"


@requires_db
def test_ambiguous_gate_lists_candidates_in_a_stable_order(config, db, fake_backend):
    _open_task(db, "call the dentist")
    _open_task(db, "book the dentist follow-up")
    o = _orch(config, db, fake_backend)
    first = o.handle("mark the dentist thing done", captured_at=NOW)
    second = o.handle("mark the dentist thing done", captured_at=NOW)
    assert first.pending.candidate_ids == second.pending.candidate_ids
    assert first.pending.candidate_ids == sorted(first.pending.candidate_ids)
    assert "1. call the dentist" in first.message


@requires_db
def test_unclear_reply_re_gates_without_closing_anything(config, db, fake_backend):
    a = _open_task(db, "call the dentist")
    b = _open_task(db, "book the dentist follow-up")
    o = _orch(config, db, fake_backend)
    gate = o.handle("mark the dentist thing done", captured_at=NOW)
    again = o.handle("hmm", captured_at=NOW, pending=gate.pending)
    assert again.intent_kind == "gate" and again.pending is not None
    assert _get(db, a).status == "open" and _get(db, b).status == "open"
