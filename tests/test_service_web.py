"""GET /web smoke endpoint — 404 when [web] disabled, wired through when on."""
from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.conversation.store import ConversationStore
from io_assistant.orchestrator import Orchestrator
from io_assistant.service.app import create_app
from io_assistant.web.search import InstantAnswer, SearchResponse


def _app(config, fake_backend, db):
    return create_app(
        config,
        orchestrator=Orchestrator(config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(),
        conversations=ConversationStore(lambda: db),
    )


@requires_db
def test_web_disabled_is_404(config, fake_backend, db):
    with TestClient(_app(config, fake_backend, db)) as c:
        assert c.get("/web", params={"q": "usd to pkr"}).status_code == 404


@requires_db
def test_web_enabled_returns_tier_a(config, fake_backend, db, monkeypatch):
    config.web.enabled = True
    config.web.provider = "searxng"

    class FakeSearcher:
        enabled = True

        def search(self, q, *, categories="general"):
            return SearchResponse(query=q, instant=[InstantAnswer(text="1 USD = 278 PKR")])

    import io_assistant.web.answer as answer_mod
    monkeypatch.setattr(answer_mod, "WebSearcher", lambda cfg: FakeSearcher())

    with TestClient(_app(config, fake_backend, db)) as c:
        r = c.get("/web", params={"q": "usd to pkr", "kind": "fact"})
        assert r.status_code == 200
        body = r.json()
        assert body["tier"] == "a"
        assert "278 PKR" in body["text"]
        assert c.get("/web", params={"q": "x", "kind": "bogus"}).status_code == 400
