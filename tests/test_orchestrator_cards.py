import datetime as dt

from io_assistant.orchestrator_cards import query_cards
from io_assistant.query.pipeline import QueryAnswer, RecordRef
from io_assistant.models_domain import TaskListCard
from tests.conftest import requires_db

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


@requires_db
def test_tasklist_card_emitted_for_open_task_without_due(db):
    ans = QueryAnswer(text="", shape="markdown", n_rows=1, source_record_ids=[],
        list_records=[RecordRef(record_id=1, kind="task", domain="home",
                                title="mop", status="open", when=None, due=None)])
    cards = query_cards(db, ans)
    assert any(isinstance(c, TaskListCard) for c in cards)


@requires_db
def test_no_tasklist_for_pure_event_answer(db):
    ans = QueryAnswer(text="", shape="text", n_rows=1, source_record_ids=[],
        list_records=[RecordRef(record_id=1, kind="event", domain="social",
                                title="dinner", status=None, when=NOW, due=None)])
    assert not any(isinstance(c, TaskListCard) for c in query_cards(db, ans))


@requires_db
def test_tasklist_card_emitted_for_mixed_list_with_a_statusful_row(db):
    ans = QueryAnswer(text="", shape="markdown", n_rows=2, source_record_ids=[],
        list_records=[
            RecordRef(record_id=1, kind="task", domain="home",
                      title="mop", status="open", when=None, due=None),
            RecordRef(record_id=2, kind="event", domain="social",
                      title="dinner", status=None, when=NOW, due=None),
        ])
    cards = query_cards(db, ans)
    tasklists = [c for c in cards if isinstance(c, TaskListCard)]
    assert len(tasklists) == 1
    assert [i.record_id for i in tasklists[0].items] == [1]


@requires_db
def test_collection_card_emitted_for_watchlist_answer(db):
    from io_assistant.db import models as m
    from io_assistant.models_domain import CollectionCard
    from io_assistant.query.pipeline import QueryAnswer, RecordRef
    db.add(m.Collection(kind_slug="watchlist", name="watchlist",
                        item_noun="movie", synonyms=["watchlist"],
                        field_hint={"checkable": True}))
    db.flush()
    ans = QueryAnswer(text="", shape="markdown", n_rows=2, source_record_ids=[1, 2],
        list_records=[RecordRef(1, "watchlist", "other", "Dune", "open", None, None),
                      RecordRef(2, "watchlist", "other", "Barbie", "done", None, None)])
    cards = query_cards(db, ans)
    cc = [c for c in cards if isinstance(c, CollectionCard)]
    assert cc and cc[0].kind_slug == "watchlist" and len(cc[0].items) == 2
