"""In-process embedder so IO needs no Ollama. fastembed runs the same
nomic-embed-text v1.5 as Ollama's `nomic-embed-text`, so its 768-d vectors are
interchangeable with ones already stored. The model (~520 MB fp32) downloads
once from HuggingFace into config.backend.models_dir — see rules/local-first.md."""
from __future__ import annotations

import os

from io_assistant.backend.embed import EmbedError
from io_assistant.backend.local import _resolve_threads
from io_assistant.config import Config


class BuiltinEmbedder:
    def __init__(self, config: Config):
        b = config.backend
        self._name = b.builtin_embed_model
        self._cache = os.path.expanduser(b.models_dir)
        self._threads = _resolve_threads(b.num_thread)
        self._dim = config.embedding_dim
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(
                    model_name=self._name,
                    cache_dir=self._cache,
                    threads=self._threads,
                )
            except Exception as e:  # noqa: BLE001 — ImportError, download, ONNX
                raise EmbedError(f"built-in embedder unavailable: {e}") from e
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        try:
            vecs = [v.tolist() for v in model.embed(texts)]
        except Exception as e:  # noqa: BLE001
            raise EmbedError(f"built-in embed failed: {e}") from e
        for v in vecs:
            if len(v) != self._dim:
                raise EmbedError(
                    f"embedding dim {len(v)} != configured {self._dim}"
                )
        return vecs
