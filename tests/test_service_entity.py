import datetime as dt

from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.conversation.store import ConversationStore
from io_assistant.service.app import create_app
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)


@requires_db
def test_entity_panel(config, fake_backend, db):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    p = m.Person(canonical_name="Priya", aliases=[])
    db.add(p)
    db.flush()
    for i, title in enumerate(["started a ceramics class", "allergic to lilies"]):
        r = m.Record(kind="note", domain="social", title=title, attributes={},
                     occurred_at=NOW - dt.timedelta(days=i), source_utterance_id=u.id)
        db.add(r)
        db.flush()
        db.add(m.RecordPerson(record_id=r.id, person_id=p.id))
        db.flush()

    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        panel = c.get(f"/entity/person/{p.id}").json()
        missing = c.get("/entity/person/999999")
    assert panel["name"] == "Priya"
    assert len(panel["facts"]) == 2
    assert panel["facts"][0]["record_ids"]
    assert 0.0 <= panel["confidence"] <= 1.0
    assert panel["sourced_from"] == 2
    assert missing.status_code == 404


@requires_db
def test_records_browse_edit_delete(config, fake_backend, db, monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    r = m.Record(kind="fact", domain="work", title="Cypher engineer at Crenger Tech",
                 attributes={}, source_utterance_id=u.id)
    db.add(r); db.flush()
    rid = r.id

    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        rows = c.get("/records").json()
        assert any(x["id"] == rid and x["domain"] == "work" for x in rows)

        edited = c.patch(f"/record/{rid}", json={"title": "SWE at Granjur Tech",
                                                 "when_phrase": "the 10th of september"})
        assert edited.status_code == 200
        assert edited.json()["title"] == "SWE at Granjur Tech"
        assert edited.json()["when"].startswith("2026-09-10")

        assert c.delete(f"/record/{rid}").json() == {"deleted": rid}
        assert all(x["id"] != rid for x in c.get("/records").json())
        assert c.delete(f"/record/{rid}").status_code == 404


@requires_db
def test_patch_record_status_maintains_completed_at(config, fake_backend, db):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    r = m.Record(kind="task", domain="home", title="mop the floor",
                 status="open", attributes={}, source_utterance_id=u.id)
    db.add(r); db.flush(); rid = r.id

    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        done = c.patch(f"/record/{rid}", json={"status": "done"}).json()
        assert done["status"] == "done"
        db.expire_all()
        assert db.get(m.Record, rid).completed_at is not None
        c.patch(f"/record/{rid}", json={"status": "open"})
        db.expire_all()
        assert db.get(m.Record, rid).completed_at is None


@requires_db
def test_patch_record_status_rejects_bogus_value(config, fake_backend, db):
    """Finding 4: RecordEditIn.status must be constrained to the three real
    values — an arbitrary string should 422, not silently persist."""
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    r = m.Record(kind="task", domain="home", title="mop the floor",
                 status="open", attributes={}, source_utterance_id=u.id)
    db.add(r); db.flush(); rid = r.id

    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        resp = c.patch(f"/record/{rid}", json={"status": "bogus"})
        assert resp.status_code == 422
        db.expire_all()
        assert db.get(m.Record, rid).status == "open"   # unchanged


@requires_db
def test_collections_endpoint_lists_with_counts(config, fake_backend, db):
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    db.add(m.Collection(kind_slug="watchlist", name="watchlist", synonyms=["watchlist"], field_hint={"checkable": True}))
    db.add(m.Record(kind="watchlist", title="A", status="open", source_utterance_id=u.id))
    db.add(m.Record(kind="watchlist", title="B", status="done", source_utterance_id=u.id))
    db.flush()
    app = create_app(config, orchestrator=Orchestrator(config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        rows = c.get("/collections").json()
    w = next(r for r in rows if r["kind_slug"] == "watchlist")
    assert w["open_count"] == 1 and w["done_count"] == 1
