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
    ("I did the laundry", "done"),
    ("took care of the dentist appointment", "done"),
    ("I need to buy groceries", None),
    # A completion refers to something IO already knows about; an indefinite
    # object is new information, so leave it to the planner.
    ("I did a 5k run this morning", None),
    ("I finished a book last night", None),
    ("set up a meeting with Ali", None),
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


@requires_db
def test_stale_gate_never_recloses_an_already_closed_task(config, db, fake_backend):
    a = _open_task(db, "call the dentist")
    b = _open_task(db, "book the dentist follow-up")
    o = _orch(config, db, fake_backend)
    gate = o.handle("mark the dentist thing done", captured_at=NOW)
    assert gate.pending.candidate_ids == [a, b]

    closed = _get(db, a)          # closed out of band, after the gate went out
    closed.status = "dropped"
    db.flush()

    res = o.handle("the first one", captured_at=NOW, pending=gate.pending)

    a_row, b_row = _get(db, a), _get(db, b)
    assert a_row.status == "dropped" and a_row.completed_at is None
    assert b_row.status == "open"
    assert res.intent_kind == "gate" and res.pending.candidate_ids == [b]


@requires_db
def test_gate_reply_acks_when_every_candidate_is_gone(config, db, fake_backend):
    a = _open_task(db, "call the dentist")
    b = _open_task(db, "book the dentist follow-up")
    o = _orch(config, db, fake_backend)
    gate = o.handle("mark the dentist thing done", captured_at=NOW)

    for rid in (a, b):
        _get(db, rid).status = "done"
    db.flush()

    res = o.handle("the first one", captured_at=NOW, pending=gate.pending)
    assert res.intent_kind == "ack" and res.pending is None
    assert _get(db, a).completed_at is None   # untouched, not re-stamped


# --- Task 6: the complete_record capability --------------------------------

@requires_db
def test_decide_complete_record_action_closes_the_task(config, db, fake_backend):
    # Text the pre-check deliberately leaves alone, so the decide/action path
    # is what does the work here.
    config.backend.decide = "combined"
    rid = _open_task(db, "water the plants")
    fake_backend.set_decide(Plan(steps=[
        Step(kind="action", action="complete_record", args={"what": "the plants"})]))
    res = _orch(config, db, fake_backend).handle("the plants are sorted", captured_at=NOW)
    assert "decide" in fake_backend.calls
    assert _get(db, rid).status == "done" and res.intent_kind == "ack"


@requires_db
def test_complete_record_action_falls_back_to_the_utterance_text(config, db, fake_backend):
    config.backend.decide = "combined"
    rid = _open_task(db, "water the plants")
    fake_backend.set_decide(Plan(steps=[
        Step(kind="action", action="complete_record", args={})]))
    _orch(config, db, fake_backend).handle("the plants", captured_at=NOW)
    assert _get(db, rid).status == "done"


# --- Task 17: checkable collection items complete like tasks/chores --------

# --- Finding 1: speculative completion for a store step the regex precheck
# already let through (the task's own verb restated in past tense) ----------

@requires_db
def test_speculative_completion_closes_task_the_regex_precheck_missed(config, db, fake_backend):
    """'I called the dentist' restates the task's own verb, not one of the
    generic _DONE_VERB vocabulary words, so the regex precheck misses it and
    (on the default split-mode profile) the turn would otherwise be filed as
    a brand-new duplicate record. Confirm the precheck genuinely misses this
    phrasing first, so the test exercises the new store-branch fallback and
    not the existing regex path."""
    o = Orchestrator(config, session_factory=lambda: None, backend=fake_backend)
    assert o._complete_precheck("I called the dentist") is None

    rid = _open_task(db, "call the dentist")
    before = db.query(m.Record).count()
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(records=[ExtractedRecord(
        kind="note", title="I called the dentist", confidence=0.9)]))

    res = _orch(config, db, fake_backend).handle(
        "I called the dentist", captured_at=NOW)

    r = _get(db, rid)
    assert r.status == "done" and r.completed_at is not None
    assert db.query(m.Record).count() == before   # no new/duplicate record
    assert res.intent_kind == "ack"


@requires_db
def test_speculative_completion_ambiguous_gates(config, db, fake_backend):
    a = _open_task(db, "call the dentist")
    b = _open_task(db, "call the vet")
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(records=[ExtractedRecord(
        kind="note", title="I called the dentist and vet", confidence=0.9)]))

    res = _orch(config, db, fake_backend).handle(
        "I called the dentist and vet", captured_at=NOW)

    assert res.intent_kind == "gate" and res.pending is not None
    assert set(res.pending.candidate_ids) == {a, b}
    assert _get(db, a).status == "open" and _get(db, b).status == "open"


@requires_db
def test_speculative_completion_does_not_false_positive_on_a_new_note(config, db, fake_backend):
    """Negative case: an unrelated brand-new note, with unrelated open tasks
    present, must still store normally rather than close_record matching a
    false positive."""
    _open_task(db, "call the dentist")
    _open_task(db, "buy groceries")
    before = db.query(m.Record).count()
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(records=[ExtractedRecord(
        kind="note", title="Sarah's birthday is in March", confidence=0.9)]))

    res = _orch(config, db, fake_backend).handle(
        "Sarah's birthday is in March", captured_at=NOW)

    assert db.query(m.Record).filter_by(
        title="Sarah's birthday is in March").count() == 1
    assert db.query(m.Record).count() == before + 1
    assert res.intent_kind == "ack"


@requires_db
def test_speculative_completion_skipped_on_gated_store_replay(config, db, fake_backend, monkeypatch):
    """A replay of an already-gated store (confirmed=True) must not re-run
    the speculative completion check at all."""
    import io_assistant.orchestrator as orch_mod

    calls = []
    orig = orch_mod.Orchestrator._speculative_complete

    def spy(self, *a, **k):
        calls.append(1)
        return orig(self, *a, **k)

    monkeypatch.setattr(orch_mod.Orchestrator, "_speculative_complete", spy)

    rid = _open_task(db, "call the dentist")
    o = _orch(config, db, fake_backend)
    from io_assistant.orchestrator import PendingStore

    pending = PendingStore(
        utterance_id=-1,
        extraction=ExtractionResult(records=[ExtractedRecord(
            kind="note", title="I called the dentist", confidence=0.9)]),
        text="I called the dentist", source="text", captured_at=NOW,
    )
    # Simulate a real gated utterance row for existing_utterance_id to attach to.
    u = m.Utterance(text="I called the dentist", source="text", captured_at=NOW)
    db.add(u); db.flush()
    pending.utterance_id = u.id

    o.handle("I called the dentist", captured_at=NOW, pending=pending)

    assert calls == []   # never invoked on a gated-store replay
    assert _get(db, rid).status == "open"   # untouched — replay stores, doesn't complete


@requires_db
def test_watched_it_closes_a_checkable_collection_item(config, db, fake_backend):
    """_checkable_kinds() must union in Task 16's checkable_kinds(session), so
    a completion phrase closes a watchlist item the same way it closes a
    task/chore. (The existing pre-check verb list doesn't recognise "watched"
    as a done-verb — orthogonal to this task's scope — so this uses "mark ...
    done" phrasing, which the pre-check already matches.)"""
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    c = m.Collection(kind_slug="watchlist", name="watchlist",
                     synonyms=["watchlist", "movies to watch"],
                     field_hint={"checkable": True})
    r = m.Record(kind="watchlist", title="Dune Part Two", status="open",
                 source_utterance_id=u.id)
    db.add_all([c, r]); db.flush()
    res = _orch(config, db, fake_backend).handle(
        "mark Dune Part Two done", captured_at=NOW)
    assert _get(db, r.id).status == "done" and res.intent_kind == "ack"
