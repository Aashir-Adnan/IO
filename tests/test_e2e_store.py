import datetime as dt
import socket
import pytest
from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 7, 18, 0, tzinfo=dt.timezone.utc)

@requires_db
def test_arcadian_scenario_with_fake_backend(db, config, fake_backend, monkeypatch):
    from io_assistant.models_domain import (
        ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedRecord, ExtractedOccasion)
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95),
                ExtractedPerson(name="Eelian", confidence=0.92)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        occasions=[ExtractedOccasion(name="Nafay and Eelian's birthday",
                                     date_phrase=None, confidence=0.8)],
        records=[ExtractedRecord(kind="event", domain="social",
                                 title="went out to eat", when_phrase="today",
                                 people=["Nafay","Eelian"], places=["Arcadian"],
                                 occasions=["Nafay and Eelian's birthday"],
                                 attributes={"meal":"dinner"}, confidence=0.9)]))
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0]*768,
        "embed": lambda self, ts: [[0.0]*768 for _ in ts]})())
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("I went out with Nafay to eat at Arcadian for his and Eelian's birthday",
                   captured_at=NOW)
    assert res.stored and len(res.stored.record_ids) == 1
    rec = db.get(m.Record, res.stored.record_ids[0])
    assert rec.kind == "event"
    assert rec.occurred_at.date() == dt.date(2026, 9, 7)
    people = {rp.person_id for rp in db.query(m.RecordPerson).filter_by(record_id=rec.id)}
    assert len(people) == 2
    assert db.query(m.RecordPlace).filter_by(record_id=rec.id).count() == 1
    assert db.query(m.RecordOccasion).filter_by(record_id=rec.id).count() == 1

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _RecordingClient:
    """Stands in for httpx.Client: records every URL posted to, and answers
    with an Ollama-shaped payload. Opens no socket of its own."""

    urls: list[str] = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, json=None, **kw):
        _RecordingClient.urls.append(url)
        if url.endswith("/api/embed"):
            n = len(json["input"])
            return _FakeResponse({"embeddings": [[0.0] * 768 for _ in range(n)]})
        return _FakeResponse({"message": {"content": "STORE"}})


def test_local_first_no_foreign_sockets(config, monkeypatch):
    """LocalBackend + Embedder must only ever talk to localhost. Traffic is
    actually driven through the guard — construction alone proves nothing."""
    import httpx

    from io_assistant.backend.embed import Embedder
    from io_assistant.backend.local import LocalBackend

    foreign: list[str] = []
    real_connect = socket.socket.connect

    def guard(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            foreign.append(str(host))
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guard)
    _RecordingClient.urls = []
    monkeypatch.setattr(httpx, "Client", _RecordingClient)

    backend = LocalBackend(config)
    embedder = Embedder(config)
    assert backend.route("test") == "store"
    assert len(embedder.embed_one("test")) == 768

    assert _RecordingClient.urls, "no traffic was driven through the guard"
    for url in _RecordingClient.urls:
        host = httpx.URL(url).host
        assert host in ("localhost", "127.0.0.1"), f"foreign host: {host}"
    assert foreign == [], f"foreign sockets opened: {foreign}"


def test_local_provider_structurally_cannot_be_anthropic(config, monkeypatch):
    """Documents the structural half: only provider='anthropic' can ever
    produce an AnthropicBackend — local mode cannot reach the API."""
    from io_assistant.backend.anthropic_backend import AnthropicBackend
    from io_assistant.backend.factory import build_backend
    from io_assistant.backend.local import LocalBackend

    assert isinstance(build_backend(config), LocalBackend)

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    remote = config.model_copy(
        update={"backend": config.backend.model_copy(update={"provider": "anthropic"})}
    )
    assert isinstance(build_backend(remote), AnthropicBackend)  # no call made
