import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from io_assistant.service.app import create_app
from io_assistant.widgets.store import WidgetsDoc, load, save


def _doc(**kw):
    base = {"layout": [{"id": "w1", "type": "todo", "size": "M", "col": 0, "row": 0}],
            "settings": {"timezones": ["Asia/Karachi"]}}
    return {**base, **kw}


def test_missing_file_loads_as_none(tmp_path):
    assert load(tmp_path / "widgets.json") is None


def test_save_then_load_round_trips(tmp_path):
    p = tmp_path / "sub" / "widgets.json"
    save(p, WidgetsDoc(**_doc()))
    got = load(p)
    assert got["layout"][0]["type"] == "todo"
    assert got["settings"] == {"timezones": ["Asia/Karachi"]}


def test_a_corrupt_file_is_treated_as_missing(tmp_path):
    p = tmp_path / "widgets.json"
    p.write_text("{not json")
    assert load(p) is None


@pytest.mark.parametrize("bad", [
    _doc(layout=[{"id": "x", "type": "evil", "size": "M", "col": 0, "row": 0}]),
    _doc(layout=[{"id": "x", "type": "todo", "size": "XL", "col": 0, "row": 0}]),
    _doc(layout=[{"id": f"w{i}", "type": "todo", "size": "S", "col": 0, "row": i}
                 for i in range(25)]),
    _doc(settings={"blob": "x" * 30_000}),
])
def test_invalid_documents_are_rejected(bad):
    with pytest.raises(ValidationError):
        WidgetsDoc(**bad)


def test_endpoints_persist_the_layout(config, tmp_path):
    app = create_app(config, orchestrator=object(), engine=object(),
                     conversations=object(), voice=object())
    app.state.widgets_path = tmp_path / "widgets.json"
    with TestClient(app) as c:
        assert c.get("/widgets").json() == {"layout": None, "settings": {}}
        assert c.put("/widgets", json=_doc()).json() == {"ok": True}
        got = c.get("/widgets").json()
        assert got["layout"][0]["id"] == "w1" and got["settings"]["timezones"] == ["Asia/Karachi"]
        assert c.put("/widgets", json=_doc(layout=[{"id": "x", "type": "evil",
                                                    "size": "S", "col": 0, "row": 0}])
                     ).status_code == 422
    assert json.loads((tmp_path / "widgets.json").read_text())["layout"][0]["id"] == "w1"
