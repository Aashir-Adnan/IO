import types

from io_assistant.query.respond import Responder, rows_to_json
from io_assistant.query.rank import RankedRow


def test_empty_rows_short_circuits(fake_backend):
    out = Responder(fake_backend).run("what did I do?", [], "text")
    assert "anything" in out.lower()
    assert "phrase" not in fake_backend.calls


def test_calls_backend_with_projected_rows(fake_backend):
    fake_backend.set_answer("You had dinner with Nafay.")
    row = RankedRow(
        types.SimpleNamespace(title="dinner", kind="event", domain="social",
                              status=None, occurred_at=None, due_at=None,
                              created_at=None, name=None, date=None),
        "record", "both", 0.9,
    )
    out = Responder(fake_backend).run("dinner?", [row], "text")
    assert out == "You had dinner with Nafay."
    assert "phrase" in fake_backend.calls


def test_rows_to_json_projects_record():
    row = RankedRow(
        types.SimpleNamespace(title="pay rent", kind="task", domain="home",
                              status="open", occurred_at=None, due_at=None,
                              created_at=None, name=None, date=None),
        "record", "structured", 0.5,
    )
    d = rows_to_json([row])[0]
    assert d["type"] == "record" and d["title"] == "pay rent" and d["status"] == "open"
