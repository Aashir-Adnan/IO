import datetime as dt

from tests.conftest import requires_db
from io_assistant.backend.embed import EmbedError
from io_assistant.backend.backfill import backfill_embeddings
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.timezone.utc)


class Flaky:
    def __init__(self, up):
        self.up = up

    def embed(self, ts):
        if not self.up:
            raise EmbedError("down")
        return [[0.25] * 768 for _ in ts]

    def embed_one(self, t):
        return self.embed([t])[0]


def _seed(db):
    u = m.Utterance(text="s", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    db.add_all([
        m.Person(canonical_name="Nafay", aliases=[]),
        m.Place(name="Hunza", aliases=[]),
        m.Record(kind="note", title="gym", body="leg day", occurred_at=NOW,
                 attributes={}, source_utterance_id=u.id),
    ])
    db.flush()


@requires_db
def test_backfill_fills_null_embeddings(db):
    _seed(db)
    n = backfill_embeddings(db, Flaky(up=True))
    assert n == 3
    assert db.query(m.Person).one().embedding is not None
    assert db.query(m.Record).one().embedding is not None
    assert backfill_embeddings(db, Flaky(up=True)) == 0   # idempotent


@requires_db
def test_backfill_stops_quietly_when_embedder_down(db):
    _seed(db)
    assert backfill_embeddings(db, Flaky(up=False)) == 0
    assert db.query(m.Person).one().embedding is None
