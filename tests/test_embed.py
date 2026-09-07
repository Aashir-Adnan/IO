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
