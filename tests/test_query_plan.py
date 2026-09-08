import datetime as dt
import json
from pathlib import Path

import pytest

from io_assistant.query.plan import ground_plan, QueryPlan, PlanError

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)  # a Tuesday
FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "questions_plan.json").read_text()
)


@pytest.mark.parametrize("case", FIXTURES, ids=lambda c: c["question"][:30])
def test_ground_plan_fixtures(case):
    plan = ground_plan(case["raw"], NOW)
    assert isinstance(plan, QueryPlan)
    exp = case["expect"]
    assert len(plan.subqueries) == exp["n_subqueries"]
    if "kind_filter" in exp:
        assert plan.subqueries[0].kind_filter == exp["kind_filter"]
    if "entities" in exp:
        assert plan.subqueries[0].entities == exp["entities"]
    if "window_start_date" in exp:
        assert plan.subqueries[0].time_window.start.date().isoformat() == exp["window_start_date"]
        assert plan.subqueries[0].time_window.end.date().isoformat() == exp["window_end_date"]
    if "domain_filter_0" in exp:
        assert plan.subqueries[0].domain_filter == exp["domain_filter_0"]
    if "kind_filter_1" in exp:
        assert plan.subqueries[1].kind_filter == exp["kind_filter_1"]
    if "answer_shape" in exp:
        assert plan.answer_shape == exp["answer_shape"]


def test_ground_plan_rejects_non_dict():
    with pytest.raises(PlanError):
        ground_plan("not a dict", NOW)


def test_ground_plan_drops_unknown_domain():
    plan = ground_plan(
        {"subqueries": [{"target_type": "record", "domain_filter": ["astrology", "job"]}]},
        NOW,
    )
    assert plan.subqueries[0].domain_filter == ["job"]
