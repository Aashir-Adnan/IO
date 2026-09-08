"""Load repo-root `.env` into the process environment, once.

Kept out of ``config.load_config`` on purpose: the test suite imports
``load_config`` directly and must not pick up the developer's real ``.env``.
Only the runnable entrypoints (``cli``, the service runner) call this.
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["load_env_once"]

_LOADED = False


def load_env_once() -> None:
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
