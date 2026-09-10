"""Web-answers routing in the orchestrator: the regex pre-check, the fall
-through when the web can't help, and the `web` decide-action."""
from __future__ import annotations

import datetime as dt

import pytest

from tests.conftest import StubEmbedder, requires_db
from io_assistant.actions.registry import describe_capabilities
from io_assistant.models_domain import Plan, Step
from io_assistant.orchestrator import Orchestrator
from io_assistant.web.answer import WebAnswer

NOW = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.timezone.utc)


class FakeAnswerer:
    def __init__(self, ans: WebAnswer | None):
        self._ans = ans
        self.calls: list[tuple[str, str]] = []

    def answer(self, session, question, *, kind, now):
        self.calls.append((question, kind))
        return self._ans


def _orch(config, fake_backend, db, answer: WebAnswer | None):
    config.web.enabled = True
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    o._embedder = StubEmbedder()
    o._web_answerer_cached = FakeAnswerer(answer)
    return o


# --- pre-check classification ----------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("what's the news on Korea", "news"),
    ("latest on the election", "news"),
    ("what's the price of petrol today compared to yesterday", "fact"),
    ("how much is a Tesla Model 3", "fact"),
    ("USD to PKR", "fact"),
    ("what do I need to do today?", None),        # first-person -> personal
    ("how's my gym been going?", None),
    ("I had coffee with Priya", None),
    ("hello there", None),
])
def test_web_precheck(config, fake_backend, text, expected):
    config.web.enabled = True
    o = Orchestrator(config, session_factory=lambda: None, backend=fake_backend)
    assert o._web_precheck(text) == expected


def test_web_precheck_off_when_disabled(config, fake_backend):
    config.web.enabled = False
    o = Orchestrator(config, session_factory=lambda: None, backend=fake_backend)
    assert o._web_precheck("what's the news on Korea") is None


# --- end to end -----------------------------------------------------------
@requires_db
def test_precheck_answers_from_web(config, fake_backend, db):
    ans = WebAnswer(text="Seoul saw talks resume today.", kind="news", tier="c",
                    sources=[{"title": "KH", "url": "https://kh.test/a"}])
    o = _orch(config, fake_backend, db, ans)

    res = o.handle("what's the news on Korea")
    assert res.intent_kind == "answer"
    assert res.message == "Seoul saw talks resume today."
    assert res.cards and res.cards[0].type == "web"
    assert res.cards[0].sources[0].url == "https://kh.test/a"
    assert o._web_answerer_cached.calls == [("what's the news on Korea", "news")]


@requires_db
def test_precheck_falls_through_when_web_has_nothing(config, fake_backend, db):
    o = _orch(config, fake_backend, db, None)          # web returns nothing
    fake_backend.set_intent("unknown")                 # split planner -> unknown

    res = o.handle("what's the news on Korea")
    assert res.intent_kind == "unknown"
    assert o._web_answerer_cached.calls                # web was tried first


@requires_db
def test_web_decide_action(config, fake_backend, db):
    config.backend.provider = "anthropic"              # combined mode
    ans = WebAnswer(text="Petrol is 290 PKR/L.", kind="fact", tier="c", sources=[])
    o = _orch(config, fake_backend, db, ans)
    fake_backend.set_decide(Plan(steps=[
        Step(kind="action", action="web", args={"query": "petrol price", "kind": "fact"}),
    ]))

    # phrasing that dodges the regex pre-check so the planner runs
    res = o.handle("give me the going rate for a litre of petrol")
    assert res.message == "Petrol is 290 PKR/L."
    assert res.cards[0].type == "web"


def test_capabilities_gate_web():
    assert "web:" not in describe_capabilities(files_enabled=False)
    assert "web:" in describe_capabilities(files_enabled=False, web_enabled=True)
    assert "track:" in describe_capabilities(files_enabled=False, web_enabled=True)


# --- Tier B: trackers ---------------------------------------------------
class _FakeSearcher:
    def __init__(self, text):
        self._text = text

    def search(self, q, *, categories="general"):
        from io_assistant.web.search import InstantAnswer, SearchResponse
        return SearchResponse(query=q, instant=[InstantAnswer(text=self._text)])


@requires_db
def test_precheck_answers_delta_from_tracker_readings(config, fake_backend, db):
    from io_assistant.web.poller import poll_tracker, register_tracker
    from io_assistant.web.trackers import CATALOGUE

    t = register_tracker(db, CATALOGUE["usd-pkr"])
    db.flush()
    poll_tracker(db, _FakeSearcher("1 USD = 275.00 PKR"), t, NOW - dt.timedelta(days=1))
    poll_tracker(db, _FakeSearcher("1 USD = 278.50 PKR"), t, NOW)
    db.flush()

    o = _orch(config, fake_backend, db, None)          # Tier A/C returns nothing
    res = o.handle("what's the USD to PKR compared to yesterday")
    assert "278.50" in res.message
    assert "up 3.5" in res.message
    assert res.cards[0].type == "web" and res.cards[0].tier == "b"
    assert o._web_answerer_cached.calls == []          # never reached Tier A/C


@requires_db
def test_track_action_registers_and_acks(config, fake_backend, db, monkeypatch):
    import io_assistant.web.poller as poller_mod

    def fake_poll(session, searcher, tracker, now):
        tracker.last_value, tracker.last_unit, tracker.last_polled_at = "63000", "", now
        return True

    monkeypatch.setattr(poller_mod, "poll_tracker", fake_poll)
    o = _orch(config, fake_backend, db, None)

    res = o.handle("track the bitcoin price")
    assert res.intent_kind == "ack"
    assert "tracking bitcoin" in res.message.lower()

    from io_assistant.db import models as m
    rows = db.execute(m.Tracker.__table__.select()).fetchall()
    assert any(r.label == "Bitcoin price (USD)" for r in rows)
