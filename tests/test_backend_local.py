import datetime as dt
import httpx
import pytest
from io_assistant.backend.local import LocalBackend, BackendParseError

def _patch_chat(monkeypatch, content: str):
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": content}}
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json): FakeClient.last = json; return FakeResp()
    monkeypatch.setattr(httpx, "Client", FakeClient)
    return FakeClient

def test_route_parses_intent(config, monkeypatch):
    _patch_chat(monkeypatch, "STORE")
    assert LocalBackend(config).route("I ate at Arcadian") == "store"

def test_route_unknown_on_garbage(config, monkeypatch):
    _patch_chat(monkeypatch, "banana pudding")
    assert LocalBackend(config).route("???") == "unknown"

def test_extract_parses_result(config, monkeypatch):
    _patch_chat(monkeypatch, '{"people":[{"name":"Nafay","aliases":[],"confidence":0.9}],'
                             '"places":[],"items":[],"occasions":[],"records":[]}')
    r = LocalBackend(config).extract("saw Nafay", dt.datetime.now(dt.timezone.utc))
    assert r.people[0].name == "Nafay"

def test_extract_bad_json_raises(config, monkeypatch):
    _patch_chat(monkeypatch, "not json at all")
    with pytest.raises(BackendParseError):
        LocalBackend(config).extract("x", dt.datetime.now(dt.timezone.utc))

def test_chat_sets_num_thread_and_keep_alive(config, monkeypatch):
    fc = _patch_chat(monkeypatch, "QUERY")
    LocalBackend(config).route("what did I do today")
    assert "num_thread" in fc.last["options"]
    assert fc.last["keep_alive"] == "30s"


def test_chat_wraps_malformed_body(config, monkeypatch):
    from io_assistant.backend.local import LocalBackendError

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"error": "model 'x' not found"}
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): return FakeResp()
    monkeypatch.setattr(httpx, "Client", FakeClient)

    with pytest.raises(LocalBackendError):
        LocalBackend(config).route("hello")


def test_local_plan_parses_json(config, monkeypatch):
    _patch_chat(monkeypatch, '{"subqueries": [], "answer_shape": "text"}')
    out = LocalBackend(config).plan("what did I do", dt.datetime.now(dt.timezone.utc))
    assert out == {"subqueries": [], "answer_shape": "text"}


def test_local_plan_bad_json_raises(config, monkeypatch):
    _patch_chat(monkeypatch, "not json")
    with pytest.raises(BackendParseError):
        LocalBackend(config).plan("x", dt.datetime.now(dt.timezone.utc))


def test_local_phrase_returns_text(config, monkeypatch):
    _patch_chat(monkeypatch, "You did leg day yesterday.")
    out = LocalBackend(config).phrase("gym?", [{"title": "leg day"}], "text")
    assert out == "You did leg day yesterday."


def test_local_route_includes_context(config, monkeypatch):
    fc = _patch_chat(monkeypatch, "QUERY")
    LocalBackend(config).route("and Sana?", context="you: what about Nafay\nio: ok")
    user_msg = fc.last["messages"][-1]["content"]
    assert "Recent conversation" in user_msg and "Nafay" in user_msg


def test_local_acknowledge_returns_line(config, monkeypatch):
    _patch_chat(monkeypatch, "Logged your dinner with Nafay.")
    assert LocalBackend(config).acknowledge('event "dinner"; with Nafay') == "Logged your dinner with Nafay."
