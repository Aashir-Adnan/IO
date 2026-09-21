"""Fill NULL embeddings once an embedder becomes available. Rows are written
without a vector when no embedder works (see embed_or_none); rows arriving from
another device (memory sync) also have none."""
from __future__ import annotations

import threading

from sqlalchemy import select

from io_assistant.backend.embed import EmbedError
from io_assistant.db import models as m

# (model, text-of-row) — same text the writers embed
_TARGETS = (
    (m.Person, lambda r: r.canonical_name),
    (m.Place, lambda r: r.name),
    (m.Item, lambda r: r.name),
    (m.Occasion, lambda r: r.name),
    (m.Record, lambda r: (r.title + "\n" + (r.body or "")).strip()),
)


def backfill_embeddings(session, embedder, *, batch: int = 32) -> int:
    filled = 0
    for model, text_of in _TARGETS:
        while True:
            rows = session.execute(
                select(model).where(model.embedding.is_(None)).limit(batch)
            ).scalars().all()
            if not rows:
                break
            try:
                vecs = embedder.embed([text_of(r) for r in rows])
            except EmbedError:
                return filled
            for r, v in zip(rows, vecs):
                r.embedding = v
            session.flush()
            filled += len(rows)
    return filled


class EmbeddingBackfiller:
    """Daemon thread, modelled on TrackerPoller: best-effort, never raises."""

    def __init__(self, session_factory, embedder, *, tick_s: float = 300.0):
        self._sf = session_factory
        self._embedder = embedder
        self._tick = tick_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def run_once(self) -> int:
        try:
            session = self._sf()
            try:
                n = backfill_embeddings(session, self._embedder)
                session.commit()
                return n
            finally:
                session.close()
        except Exception:  # pragma: no cover — worker must not die
            return 0

    def _run(self) -> None:
        if self._stop.wait(10.0):   # let startup finish first
            return
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self._tick)
