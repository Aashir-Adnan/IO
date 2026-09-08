import httpx
import pytest
from io_assistant.backend.local import LocalBackend
from io_assistant.backend.interface import Backend, BackendParseError


def _patch_chat(monkeypatch, content):
    class R:
        def raise_for_status(self): ...
        def json(self): return {"message": {"content": content}}

    class C:
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json): C.last = json; return R()

    monkeypatch.setattr(httpx, "Client", C)
    return C


def test_fakebackend_still_satisfies_protocol(fake_backend):
    assert isinstance(fake_backend, Backend)


def test_summarize_file_parses(config, monkeypatch):
    _patch_chat(monkeypatch, '{"summary":"A lease.","names":["Mr Khan"],"references":["bill.pdf"]}')
    out = LocalBackend(config).summarize_file("Lease", "the lease text")
    assert out["summary"] == "A lease."
    assert out["names"] == ["Mr Khan"]
    assert out["references"] == ["bill.pdf"]


def test_summarize_file_bad_json_raises(config, monkeypatch):
    _patch_chat(monkeypatch, "not json")
    with pytest.raises(BackendParseError):
        LocalBackend(config).summarize_file("x", "y")


def test_answer_from_files_calls_model(config, monkeypatch):
    _patch_chat(monkeypatch, "Your lease allows pets with a deposit.")
    ans = LocalBackend(config).answer_from_files(
        "pets?", [{"path": "/x/lease.md", "title": "Lease",
                   "summary": "s", "excerpts": ["Pets are allowed with a deposit."]}],
        "text")
    assert "pets" in ans.lower()


def test_fake_setters(fake_backend):
    fake_backend.set_file_summary({"summary": "s", "names": ["Nafay"], "references": []})
    fake_backend.set_file_answer("done")
    assert fake_backend.summarize_file("t", "h")["names"] == ["Nafay"]
    assert fake_backend.answer_from_files("q", [{"path": "/a"}], "text") == "done"
    assert fake_backend.last_files == [{"path": "/a"}]
