import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.query.plan import SubQuery, TimeWindow
from io_assistant.query.retrieve import retrieve_subquery

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)
EMPTY = {"person": [], "place": [], "item": [], "occasion": []}


class VecEmbedder:
    def __init__(self, vec):
        self.vec = vec

    def embed_one(self, t):
        return self.vec

    def embed(self, ts):
        return [self.vec for _ in ts]


def _uid(db):
    u = m.Utterance(text="s", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    return u.id


@requires_db
def test_retrieve_unions_structured_and_semantic(db):
    uid = _uid(db)
    near = m.Record(kind="note", title="gym leg day", occurred_at=NOW, attributes={},
                    source_utterance_id=uid, embedding=[1.0] + [0.0] * 767)
    # no embedding -> reachable by the structured spine only
    far = m.Record(kind="note", title="tax return", occurred_at=NOW, attributes={},
                   source_utterance_id=uid, embedding=None)
    db.add_all([near, far])
    db.flush()
    sq = SubQuery(target_type="record", kind_filter=["note"], semantic_hint="workout",
                  time_window=TimeWindow(start=NOW - dt.timedelta(days=1), end=NOW))
    rows = retrieve_subquery(db, VecEmbedder([1.0] + [0.0] * 767), sq, EMPTY, NOW)
    by_title = {r.obj.title: r for r in rows}
    assert by_title["gym leg day"].provenance == "both"
    assert by_title["tax return"].provenance == "structured"
    assert by_title["gym leg day"].distance is not None
