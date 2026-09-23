"""Turn-progress breadcrumbs.

A request handler binds a callback with `progress_to(cb)`; anything running
inside that block (the planner, query pipeline, file search, web path) calls
`emit("stage", "detail")` and the callback receives it. Delivered over the
`/ws` turn socket as `{"type": "progress", ...}` so the chat can show a live
log while a message is being worked on.

A `contextvars.ContextVar` carries the callback, so no function in the pipeline
needs a new parameter. It is thread-local-ish: `asyncio.to_thread` copies the
context, so the callback set inside `Orchestrator.handle` (running in the
worker thread) is visible to every `emit` in that same call stack.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Callable

__all__ = ["emit", "progress_to", "ProgressCB"]

ProgressCB = Callable[[str, str], None]

_current: contextvars.ContextVar[ProgressCB | None] = contextvars.ContextVar(
    "io_progress", default=None
)


def emit(stage: str, detail: str = "") -> None:
    cb = _current.get()
    if cb is None:
        return
    try:
        cb(str(stage), str(detail))
    except Exception:  # noqa: BLE001 — a broken listener must never break a turn
        pass


@contextmanager
def progress_to(cb: ProgressCB | None):
    token = _current.set(cb)
    try:
        yield
    finally:
        _current.reset(token)
