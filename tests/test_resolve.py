from tests.conftest import requires_db
from io_assistant.resolve.resolver import EntityResolver
from io_assistant.db import models as m
from sqlalchemy import select


class StubEmbedder:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def embed_one(self, text):
        return self.mapping.get(text, [0.0] * 768)

    def embed(self, texts):
        return [self.embed_one(t) for t in texts]


@requires_db
def test_exact_match(db, config):
    db.add(m.Person(canonical_name="Nafay", aliases=["naf"]))
    db.flush()
    r = EntityResolver(db, StubEmbedder(), config.resolver)
    out = r.resolve("person", "nafay", [])
    assert out.entity_id is not None and not out.is_new and not out.ambiguous


@requires_db
def test_alias_match(db, config):
    db.add(m.Person(canonical_name="Mother", aliases=["mum", "mom"]))
    db.flush()
    out = EntityResolver(db, StubEmbedder(), config.resolver).resolve("person", "Mum", [])
    assert out.entity_id is not None


@requires_db
def test_fuzzy_match(db, config):
    db.add(m.Place(name="Blue Bottle Coffee", type=None, aliases=[]))
    db.flush()
    out = EntityResolver(db, StubEmbedder(), config.resolver).resolve("place", "Blue Bottle", [])
    assert out.entity_id is not None


@requires_db
def test_vector_ambiguous(db, config):
    p = m.Person(canonical_name="Jonathan", aliases=[], embedding=[1.0] + [0.0] * 767)
    db.add(p)
    db.flush()
    emb = StubEmbedder({"Jon": [1.0] + [0.0] * 767})
    out = EntityResolver(db, emb, config.resolver).resolve("person", "Jon", [])
    assert out.ambiguous and out.candidate_name == "Jonathan" and out.entity_id is None


@requires_db
def test_new_entity(db, config):
    out = EntityResolver(db, StubEmbedder(), config.resolver).resolve("person", "Zephyr", [])
    assert out.is_new and out.entity_id is None


@requires_db
def test_incoming_alias_matches_stored_canonical(db, config):
    db.add(m.Person(canonical_name="Muhammad Nafay", aliases=[]))
    db.flush()
    out = EntityResolver(db, StubEmbedder(), config.resolver).resolve(
        "person", "Nafay Khan", ["Muhammad Nafay"]
    )
    assert out.entity_id is not None and not out.is_new


@requires_db
def test_fuzzy_matches_against_stored_alias(db, config):
    # canonical is unrelated; only the stored alias is a strong fuzzy match
    db.add(m.Item(name="X-1000", category=None, aliases=["Blue Bottle Coffee"]))
    db.flush()
    out = EntityResolver(db, StubEmbedder(), config.resolver).resolve(
        "item", "Blue Bottle Coffee Co", []
    )
    assert out.entity_id is not None and not out.is_new


@requires_db
def test_resolve_does_not_full_scan(db, config, monkeypatch):
    from io_assistant.resolve import resolver as rmod

    for i in range(60):
        db.add(m.Person(canonical_name=f"Person Number {i}", aliases=[]))
    db.flush()

    seen = {}
    real = rmod.EntityResolver._candidate_rows

    def spy(self, etype, name, aliases):
        rows = real(self, etype, name, aliases)
        seen["n"] = len(rows)
        return rows

    monkeypatch.setattr(rmod.EntityResolver, "_candidate_rows", spy)
    rmod.EntityResolver(db, StubEmbedder(), config.resolver).resolve(
        "person", "Totally Unrelated Name", []
    )
    assert seen["n"] <= 50


@requires_db
def test_create_inserts_with_embedding(db, config):
    emb = StubEmbedder({"Zephyr": [0.5] + [0.0] * 767})
    r = EntityResolver(db, emb, config.resolver)
    new_id = r.create("person", "Zephyr", [])
    assert isinstance(new_id, int)
    row = db.execute(select(m.Person).where(m.Person.id == new_id)).scalar_one()
    assert row.canonical_name == "Zephyr"
    assert row.embedding is not None
