from __future__ import annotations

import httpx

from io_assistant.config import Config


class EmbedError(Exception):
    pass


class Embedder:
    def __init__(self, config: Config):
        self._url = config.backend.ollama_url.rstrip("/") + "/api/embed"
        self._model = config.backend.embed_model
        self._dim = config.embedding_dim
        self._keep_alive = config.backend.ollama_keep_alive

    def embed(self, texts: list[str]) -> list[list[float]]:
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
            raise EmbedError(f"ollama embed failed: {e}") from e
        vecs = data.get("embeddings") or []
        if len(vecs) != len(texts):
            raise EmbedError(f"expected {len(texts)} vectors, got {len(vecs)}")
        for v in vecs:
            if len(v) != self._dim:
                raise EmbedError(
                    f"embedding dim {len(v)} != configured {self._dim}"
                )
        return vecs

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
