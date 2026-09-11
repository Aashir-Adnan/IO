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


@requires_db
def test_family_query_passes_names_and_body_to_phrasing(db, config, fake_backend):
    """Regression: "who is my family" returned a person-target plan whose rows
    reached the phrasing model with title=null (Person uses canonical_name) and
    no body — so the model refused. The row JSON must carry both now."""
    u = m.Utterance(text="my family", source="text", captured_at=NOW)
    db.add(u); db.flush()
    people = []
    for name in ("Mehnaz Afzal", "Adnan Afzal", "Zoha Adnan"):
        p = m.Person(canonical_name=name, aliases=[])
        db.add(p); db.flush()
        people.append(p)
    r = m.Record(
        kind="fact", domain="social", title="Family relationships",
        body="Mother is Mehnaz Afzal, father is Adnan Afzal (physiotherapist), "
             "sister is Zoha Adnan",
        attributes={}, source_utterance_id=u.id,
    )
    db.add(r); db.flush()
    for p in people:
        db.add(m.RecordPerson(record_id=r.id, person_id=p.id))
    db.flush()

    fake_backend.set_plan({
        "subqueries": [{"target_type": "record", "domain_filter": ["social"],
                        "semantic_hint": "family relationships"}],
        "answer_shape": "text",
    })
    fake_backend.set_answer("Your mother is Mehnaz Afzal, your father Adnan Afzal, "
                            "your sister Zoha Adnan.")

    pipe = QueryPipeline(fake_backend, _Emb(), config.resolver)
    ans = pipe.answer(db, "who is my family?", NOW)

    blob = str(fake_backend.last_phrase_rows)
    assert "Mehnaz Afzal" in blob and "physiotherapist" in blob
    assert "Zoha Adnan" in ans.text


@requires_db
def test_person_target_rows_carry_the_name(db, config, fake_backend):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    db.add(m.Person(canonical_name="Priya", aliases=[], notes="ceramics friend"))
    db.flush()

    fake_backend.set_plan({"subqueries": [{"target_type": "person"}],
                           "answer_shape": "text"})
    fake_backend.set_answer("Priya.")
    QueryPipeline(fake_backend, _Emb(), config.resolver).answer(db, "who is Priya?", NOW)

    row = next(x for x in fake_backend.last_phrase_rows if x["type"] == "person")
    assert row["title"] == "Priya"
    assert row["notes"] == "ceramics friend"


@requires_db
def test_planner_sees_known_lists_and_seen_kinds_in_context(db, fake_backend, config, stub_embedder):
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    db.add(m.Collection(kind_slug="watchlist", name="watchlist",
                        synonyms=["watchlist", "movies to watch"], field_hint={}))
    for i in range(3):
        db.add(m.Record(kind="giftlist", title=f"gift {i}", source_utterance_id=u.id))
    db.flush()
    # kind_filter matches nothing, so retrieval comes back empty and the
    # Responder short-circuits without calling backend.phrase() — otherwise
    # that later call would overwrite FakeBackend.last_context with the
    # plain (unchanged) `context` it receives, masking the planner's context.
    fake_backend.set_plan({"subqueries": [{"target_type": "record",
                                           "kind_filter": ["nonexistent"]}],
                           "answer_shape": "text"})
    QueryPipeline(fake_backend, stub_embedder, config.resolver).answer(
        db, "what's on my watchlist", NOW, context="prior turn")
    ctx = fake_backend.last_context or ""
    assert "Known lists" in ctx and "watchlist" in ctx
    assert "Seen kinds" in ctx and "giftlist" in ctx


@requires_db
def test_count_aggregation_reports_a_number(db, fake_backend, config, stub_embedder):
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    for i in range(4):
        db.add(m.Record(kind="watchlist", title=f"film {i}", status="open",
                        source_utterance_id=u.id))
    db.flush()
    fake_backend.set_plan({"subqueries": [
        {"target_type": "record", "kind_filter": ["watchlist"], "aggregation": "count"}],
        "answer_shape": "text"})
    fake_backend.set_answer("You have 4.")
    ans = QueryPipeline(fake_backend, stub_embedder, config.resolver).answer(
        db, "how many films on my list", NOW)
    assert ans.count == 4
