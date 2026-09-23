import datetime as dt

from tests.conftest import requires_db
from io_assistant.backend.embed import EmbedError
from io_assistant.db import models as m
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedRecord)
from io_assistant.persist.writer import persist_store
from io_assistant.query.plan import SubQuery
from io_assistant.query.retrieve import retrieve_subquery
from io_assistant.resolve.resolver import EntityResolver

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.timezone.utc)
EMPTY = {"person": [], "place": [], "item": [], "occasion": []}


class DownEmbedder:
    def embed_one(self, t):
        raise EmbedError("no embedder")

    def embed(self, ts):
        raise EmbedError("no embedder")


@requires_db
def test_resolver_create_and_exact_match_work_without_embedder(db, config):
    r = EntityResolver(db, DownEmbedder(), config.resolver)
    pid = r.create("person", "Nafay", [])
    assert db.get(m.Person, pid).embedding is None
    out = r.resolve("person", "nafay", [])       # exact, case-insensitive
    assert out.entity_id == pid and not out.is_new


@requires_db
def test_resolver_unknown_name_is_new_without_embedder(db, config):
    r = EntityResolver(db, DownEmbedder(), config.resolver)
    out = r.resolve("person", "Zebulon Quux", [])
    assert out.is_new and out.entity_id is None


@requires_db
def test_lookup_falls_back_to_fuzzy_without_embedder(db, config):
    r = EntityResolver(db, DownEmbedder(), config.resolver)
    pid = r.create("person", "Eelian Hart", [])
    assert r.lookup("person", "Eelian Hart") == pid
    assert r.lookup("person", "Qwertyuiop") is None


@requires_db
def test_retrieve_semantic_branch_skipped_without_embedder(db):
    u = m.Utterance(text="s", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    db.add(m.Record(kind="note", title="gym leg day", occurred_at=NOW,
                    attributes={}, source_utterance_id=u.id))
    db.flush()
    sq = SubQuery(target_type="record", kind_filter=["note"], semantic_hint="workout")
    rows = retrieve_subquery(db, DownEmbedder(), sq, EMPTY, NOW)
    assert [r.obj.title for r in rows] == ["gym leg day"]   # structured spine only
    assert all(r.provenance == "structured" for r in rows)


@requires_db
def test_persist_store_writes_null_embeddings_without_embedder(db, config):
    emb = DownEmbedder()
    res = persist_store(
        db, emb, EntityResolver(db, emb, config.resolver),
        utterance_text="lunch with Nafay", source="text", captured_at=NOW,
        extraction=ExtractionResult(
            people=[ExtractedPerson(name="Nafay", confidence=0.95)],
            records=[ExtractedRecord(kind="event", title="lunch with Nafay",
                                     people=["Nafay"], confidence=0.9)]),
        now=NOW, confidence_gate=0.6)
    assert res is not None
    rec = db.query(m.Record).filter_by(title="lunch with Nafay").one()
    assert rec.embedding is None
    assert db.query(m.Person).filter_by(canonical_name="Nafay").one().embedding is None
