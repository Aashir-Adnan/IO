import datetime as dt
import types

from io_assistant.query.rank import RankedRow
from io_assistant.query.recur import expand_recurrences, RecurrenceInstance

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)  # Tuesday


def _rr(rule, anchor_days_ago=60):
    obj = types.SimpleNamespace(
        id=1, title="trash", recurrence_rule=rule,
        occurred_at=None, due_at=None, date=None,
        created_at=NOW - dt.timedelta(days=anchor_days_ago),
    )
    return RankedRow(obj, "record", "structured", 0.5)


def test_weekly_rule_expands_within_window():
    out = expand_recurrences([_rr("FREQ=WEEKLY;BYDAY=MO")],
                             NOW - dt.timedelta(days=21), NOW, now=NOW)
    insts = [x for x in out if isinstance(x, RecurrenceInstance)]
    assert len(insts) == 3
    assert all(i.occurs_at.weekday() == 0 for i in insts)


def test_non_recurring_passes_through():
    plain = RankedRow(types.SimpleNamespace(id=2, recurrence_rule=None), "record", "both", 0.9)
    out = expand_recurrences([plain], None, None, now=NOW)
    assert out == [plain]


def test_unparseable_rule_passes_through():
    bad = _rr("FREQ=NONSENSE")
    out = expand_recurrences([bad], NOW - dt.timedelta(days=7), NOW, now=NOW)
    assert out == [bad]
