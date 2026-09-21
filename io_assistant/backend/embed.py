from __future__ import annotations

import logging
import time

import httpx

from io_assistant.config import Config

log = logging.getLogger(__name__)

# after a failure, don't retry that embedder for this long (avoids a slow
# connect / model-load attempt on every single embed call)
_RETRY_S = 60.0


class EmbedError(Exception):
    pass


class OllamaUnavailable(EmbedError):
    """Ollama couldn't be reached or refused the request (not a data error)."""


class Embedder:
    def __init__(self, config: Config, *, builtin=None, clock=time.monotonic):
        b = config.backend
        self._config = config
        self._url = b.ollama_url.rstrip("/") + "/api/embed"
        self._model = b.embed_model
        self._dim = config.embedding_dim
        self._keep_alive = b.ollama_keep_alive
        self._mode = b.embedder
        self._builtin = builtin
        self._clock = clock
        self._ollama_down_until = 0.0
        self._builtin_down_until = 0.0

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._mode == "ollama":
            return self._embed_ollama(texts)
        if self._mode == "auto" and self._clock() >= self._ollama_down_until:
            try:
                return self._embed_ollama(texts)
            except OllamaUnavailable as e:
                log.info("Ollama unavailable, using built-in embedder: %s", e)
                self._ollama_down_until = self._clock() + _RETRY_S
        return self._embed_builtin(texts)

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    self._url,
                    json={
                        "model": self._model,
                        "input": texts,
                        "keep_alive": self._keep_alive,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise OllamaUnavailable(f"ollama embed failed: {e}") from e
        return self._check(data.get("embeddings") or [], texts)

    def _embed_builtin(self, texts: list[str]) -> list[list[float]]:
        if self._clock() < self._builtin_down_until:
            raise EmbedError("built-in embedder unavailable (retrying shortly)")
        if self._builtin is None:
            from io_assistant.backend.embed_builtin import BuiltinEmbedder

            self._builtin = BuiltinEmbedder(self._config)
        try:
            return self._builtin.embed(texts)
        except EmbedError:
            self._builtin_down_until = self._clock() + _RETRY_S
            raise

    def _check(self, vecs, texts) -> list[list[float]]:
        if len(vecs) != len(texts):
            raise EmbedError(f"expected {len(texts)} vectors, got {len(vecs)}")
        for v in vecs:
            if len(v) != self._dim:
                raise EmbedError(
                    f"embedding dim {len(v)} != configured {self._dim}"
                )
        return vecs


def embed_or_none(embedder, text: str) -> list[float] | None:
    """Vector for `text`, or None when no embedder is available — callers fall
    back to lexical matching and leave the column NULL for the backfill."""
    try:
        return embedder.embed_one(text)
    except EmbedError as e:
        log.warning("embeddings unavailable, continuing without a vector: %s", e)
        return None
