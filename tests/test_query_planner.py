import datetime as dt

from io_assistant.query.planner import Planner
from io_assistant.query.plan import QueryPlan

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)


def test_planner_grounds_backend_output(fake_backend):
    fake_backend.set_plan({
        "subqueries": [{"target_type": "record", "kind_filter": ["event"],
                        "entities": ["Nafay"],
                        "time_window": {"start": "last week", "end": "today"}}],
        "answer_shape": "text",
    })
    plan = Planner(fake_backend).run("where did I see Nafay", NOW)
    assert isinstance(plan, QueryPlan)
    sq = plan.subqueries[0]
    assert sq.kind_filter == ["event"] and sq.entities == ["Nafay"]
    assert sq.time_window.start.date().isoformat() == "2026-09-01"


def test_planner_falls_back_on_unparseable(fake_backend):
    from io_assistant.backend.interface import BackendParseError

    def boom(*a, **k):
        raise BackendParseError("no json")

    fake_backend.plan = boom
    plan = Planner(fake_backend).run("something vague", NOW)
    assert len(plan.subqueries) == 1
    assert plan.subqueries[0].semantic_hint == "something vague"
