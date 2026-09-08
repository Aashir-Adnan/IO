import datetime as dt
import types

from io_assistant.query.retrieve import RetrievedRow
from io_assistant.query.rank import rank

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)


def _row(rid, title, days_ago, created=None):
    return types.SimpleNamespace(
        id=rid, title=title,
        occurred_at=NOW - dt.timedelta(days=days_ago), due_at=None,
        created_at=created or (NOW - dt.timedelta(days=days_ago)),
    )


def test_both_provenance_and_recency_win():
    recent_both = RetrievedRow(_row(1, "recent+both", 1), "record", "both", 0.1)
    old_structured = RetrievedRow(_row(2, "old", 200), "record", "structured", None)
    semantic_only = RetrievedRow(_row(3, "sem", 2), "record", "semantic", 0.2)
    out = rank([[recent_both, old_structured], [semantic_only]], NOW, top_n=3)
    assert [r.obj.id for r in out][0] == 1
    assert len(out) == 3


def test_dedupe_keeps_both():
    a = RetrievedRow(_row(9, "x", 1), "record", "structured", None)
    b = RetrievedRow(_row(9, "x", 1), "record", "semantic", 0.05)
    out = rank([[a], [b]], NOW)
    assert len(out) == 1 and out[0].provenance == "both"


def test_top_n_caps():
    rows = [RetrievedRow(_row(i, str(i), i), "record", "structured", None) for i in range(50)]
    assert len(rank([rows], NOW, top_n=20)) == 20
