from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.resolve.resolver import EntityResolver
from io_assistant.query.entities import resolve_query_entities


class _Emb:
    def embed_one(self, t):
        return [0.0] * 768

    def embed(self, ts):
        return [[0.0] * 768 for _ in ts]


@requires_db
def test_resolve_query_entities(db, config):
    db.add_all([
        m.Person(canonical_name="Nafay", aliases=[]),
        m.Place(name="Arcadian", type=None, aliases=[]),
        m.Occasion(name="Nafay's birthday", date=None),
    ])
    db.flush()
    r = EntityResolver(db, _Emb(), config.resolver)
    out = resolve_query_entities(r, db, ["Nafay", "Arcadian", "Nafay's birthday", "Ghost"])
    assert len(out["person"]) == 1
    assert len(out["place"]) == 1
    assert len(out["occasion"]) == 1
    assert out["item"] == []
