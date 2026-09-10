"""Combined `decide` mode: the planner uses backend.decide, and the
orchestrator dispatches a multi-step Plan into one merged turn."""
import datetime as dt

from tests.conftest import requires_db
from io_assistant.conversation.store import ConversationStore
from io_assistant.decide.planner import DecidePlanner
from io_assistant.models_domain import (
    ExtractedRecord, ExtractionResult, Plan, Step,
)
from io_assistant.orchestrator import Orchestrator

NOW = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.timezone.utc)


def _store_step(title):
    return Step(kind="store", extraction=ExtractionResult(
        records=[ExtractedRecord(kind="task", title=title, confidence=0.9)]))


def test_planner_combined_mode_calls_decide(config, fake_backend):
    config.backend.provider = "anthropic"          # -> auto resolves to combined
    fake_backend.set_decide(Plan(steps=[_store_step("water the plants")]))
    planner = DecidePlanner(fake_backend, config)
    plan = planner.plan("remind me to water the plants", NOW)
    assert "decide" in fake_backend.calls
    assert plan.steps[0].kind == "store"


def test_planner_combined_parse_failure_falls_back_to_split(config, fake_backend):
    config.backend.provider = "anthropic"
    fake_backend.set_intent("query")               # split path will use this
    # no set_decide -> decide() raises BackendParseError -> fallback
    plan = DecidePlanner(fake_backend, config).plan("what's on friday", NOW)
    assert plan.steps[0].kind == "query"
    assert "route" in fake_backend.calls           # proves the split fallback ran


def test_local_light_stays_split(config, fake_backend):
    config.backend.provider = "local"
    config.backend.profile = "light"
    fake_backend.set_decide(Plan(steps=[_store_step("x")]))
    DecidePlanner(fake_backend, config).plan("I did a thing", NOW)
    assert "decide" not in fake_backend.calls


@requires_db
def test_orchestrator_runs_multi_step_turn(config, fake_backend, db):
    config.backend.provider = "anthropic"
    fake_backend.set_decide(Plan(steps=[
        _store_step("call mum"),
        Step(kind="query", question="what tasks do I have"),
    ]))
    fake_backend.set_ack("Noted — call mum.")
    fake_backend.set_answer("You have one task: call mum.")

    from tests.conftest import StubEmbedder
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    o._embedder = StubEmbedder()

    res = o.handle("remind me to call mum, and what are my tasks?")
    # one merged turn carrying both the ack and the answer
    assert "call mum" in res.message.lower()
    assert res.intent_kind in ("answer", "ack")
