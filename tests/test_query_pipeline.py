import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.query.pipeline import QueryPipeline

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)


class _Emb:
    def embed_one(self, t):
        return [0.0] * 768

    def embed(self, ts):
        return [[0.0] * 768 for _ in ts]


@requires_db
def test_pipeline_answers_from_stored_record(db, config, fake_backend):
    u = m.Utterance(text="dinner with Nafay", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    p = m.Person(canonical_name="Nafay", aliases=[])
    db.add(p)
    db.flush()
    r = m.Record(kind="event", domain="social", title="dinner with Nafay",
                 occurred_at=NOW - dt.timedelta(days=2), attributes={},
                 source_utterance_id=u.id)
    db.add(r)
    db.flush()
    db.add(m.RecordPerson(record_id=r.id, person_id=p.id))
    db.flush()

    fake_backend.set_plan({
        "subqueries": [{"target_type": "record", "kind_filter": ["event"],
                        "entities": ["Nafay"],
                        "time_window": {"start": "last week", "end": "today"}}],
        "answer_shape": "text",
    })
    fake_backend.set_answer("You had dinner with Nafay two days ago.")

    pipe = QueryPipeline(fake_backend, _Emb(), config.resolver)
    ans = pipe.answer(db, "when did I last see Nafay?", NOW)
    assert ans.n_rows == 1
    assert "Nafay" in ans.text
