import os
import sys
import types

import pytest

from io_assistant.backend.embed import EmbedError
from io_assistant.backend.embed_builtin import BuiltinEmbedder


class Vec(list):
    def tolist(self):
        return list(self)


def _embedder(config, vec_len):
    b = BuiltinEmbedder(config)
    b._model = types.SimpleNamespace(
        embed=lambda texts: iter([Vec([0.1] * vec_len) for _ in texts])
    )
    return b


def test_returns_vectors_of_configured_dimension(config):
    out = _embedder(config, 768).embed(["a", "b"])
    assert len(out) == 2 and len(out[0]) == 768


def test_wrong_dimension_raises(config):
    with pytest.raises(EmbedError):
        _embedder(config, 10).embed(["a"])


def test_missing_library_raises_embed_error(config, monkeypatch):
    monkeypatch.setitem(sys.modules, "fastembed", None)  # import -> ImportError
    with pytest.raises(EmbedError):
        BuiltinEmbedder(config).embed(["a"])


@pytest.mark.builtin
@pytest.mark.skipif(os.environ.get("IO_BUILTIN_EMBED_TESTS") != "1",
                    reason="opt-in (downloads ~520 MB)")
def test_real_model_dimension(config):
    v = BuiltinEmbedder(config).embed(["hello world"])[0]
    assert len(v) == config.embedding_dim


@pytest.mark.builtin
@pytest.mark.ollama
@pytest.mark.skipif(
    os.environ.get("IO_BUILTIN_EMBED_TESTS") != "1"
    or os.environ.get("IO_OLLAMA_TESTS") != "1",
    reason="opt-in (needs the model and a running Ollama)",
)
def test_builtin_matches_ollama(config):
    from io_assistant.backend.embed import Embedder

    config.backend.embedder = "ollama"
    ollama = Embedder(config).embed_one("Nafay and Eelian's birthday")
    builtin = BuiltinEmbedder(config).embed(["Nafay and Eelian's birthday"])[0]
    dot = sum(a * b for a, b in zip(ollama, builtin))
    na = sum(a * a for a in ollama) ** 0.5
    nb = sum(b * b for b in builtin) ** 0.5
    assert dot / (na * nb) > 0.98
