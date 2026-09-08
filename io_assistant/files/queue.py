from __future__ import annotations

import queue
import threading
from pathlib import Path

__all__ = ["IndexQueue"]

_STOP = object()


class IndexQueue:
    """Single-thread background file indexer for the service (resource budget:
    concurrency 1, on demand)."""

    def __init__(self, session_factory, indexer, gate):
        self._sf = session_factory
        self._indexer = indexer
        self._gate = gate
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if self._thread is None:
            return
        self._q.put(_STOP)
        self._thread.join(timeout=timeout)
        self._thread = None

    def enqueue(self, path: str) -> None:
        self._q.put(str(path))

    def enqueue_many(self, paths) -> None:
        for p in paths:
            self._q.put(str(p))

    def depth(self) -> int:
        return self._q.qsize()

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is _STOP:
                return
            try:
                session = self._sf()
                try:
                    self._indexer.index_path(session, Path(item), gate=self._gate)
                    session.commit()
                finally:
                    session.close()
            except Exception:  # pragma: no cover - worker must not die
                pass
