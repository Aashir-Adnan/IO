import os
import pytest
import httpx
from io_assistant.backend.embed import Embedder, EmbedError


def test_embed_posts_and_returns_vectors(config, monkeypatch):
    calls = {}

    class FakeResp:
        status_code = 200

        def json(self):
            return {"embeddings": [[0.1] * 768, [0.2] * 768]}

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, json):
            calls["url"] = url
            calls["json"] = json
            return FakeResp()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    out = Embedder(config).embed(["a", "b"])
    assert calls["url"].endswith("/api/embed")
    assert calls["json"]["model"] == "nomic-embed-text"
    assert len(out) == 2 and len(out[0]) == 768


def test_embed_dimension_mismatch_raises(config, monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {"embeddings": [[0.1] * 10]}

        def raise_for_status(self):
            pass

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    with pytest.raises(EmbedError):
        Embedder(config).embed(["a"])


@pytest.mark.ollama
@pytest.mark.skipif(os.environ.get("IO_OLLAMA_TESTS") != "1", reason="opt-in")
def test_embed_real_ollama(config):
    from io_assistant.backend.embed import Embedder

    v = Embedder(config).embed_one("hello world")
    assert len(v) == config.embedding_dim


class _Builtin:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[0.5] * 768 for _ in texts]


def _refuse(monkeypatch, hits=None):
    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            if hits is not None:
                hits.append(1)
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "Client", Client)


def test_auto_falls_back_to_builtin_when_ollama_down(config, monkeypatch):
    _refuse(monkeypatch)
    b = _Builtin()
    out = Embedder(config, builtin=b).embed(["a"])
    assert out == [[0.5] * 768]
    assert b.calls == [["a"]]


def test_auto_skips_ollama_for_a_minute_after_failure(config, monkeypatch):
    hits = []
    _refuse(monkeypatch, hits)
    now = [0.0]
    e = Embedder(config, builtin=_Builtin(), clock=lambda: now[0])
    e.embed(["a"])
    e.embed(["b"])
    assert len(hits) == 1
    now[0] = 61.0
    e.embed(["c"])
    assert len(hits) == 2


def test_builtin_mode_never_calls_ollama(config, monkeypatch):
    config.backend.embedder = "builtin"
    hits = []
    _refuse(monkeypatch, hits)
    Embedder(config, builtin=_Builtin()).embed(["a"])
    assert hits == []


def test_ollama_mode_has_no_fallback(config, monkeypatch):
    config.backend.embedder = "ollama"
    _refuse(monkeypatch)
    b = _Builtin()
    with pytest.raises(EmbedError):
        Embedder(config, builtin=b).embed(["a"])
    assert b.calls == []


def test_builtin_failure_raises_and_is_remembered(config, monkeypatch):
    _refuse(monkeypatch)
    calls = []

    class Broken:
        def embed(self, texts):
            calls.append(1)
            raise EmbedError("model missing")

    now = [0.0]
    e = Embedder(config, builtin=Broken(), clock=lambda: now[0])
    with pytest.raises(EmbedError):
        e.embed(["a"])
    with pytest.raises(EmbedError):
        e.embed(["b"])
    assert len(calls) == 1   # second call short-circuits inside the retry window


def test_embed_or_none_swallows_embed_error():
    from io_assistant.backend.embed import embed_or_none

    class Down:
        def embed_one(self, t):
            raise EmbedError("down")

    assert embed_or_none(Down(), "x") is None

    class Up:
        def embed_one(self, t):
            return [1.0]

    assert embed_or_none(Up(), "x") == [1.0]
