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
def test_create_inserts_with_embedding(db, config):
    emb = StubEmbedder({"Zephyr": [0.5] + [0.0] * 767})
    r = EntityResolver(db, emb, config.resolver)
    new_id = r.create("person", "Zephyr", [])
    assert isinstance(new_id, int)
    row = db.execute(select(m.Person).where(m.Person.id == new_id)).scalar_one()
    assert row.canonical_name == "Zephyr"
    assert row.embedding is not None
