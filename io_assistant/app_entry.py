"""Frozen-app entry point (PyInstaller). Thin wrapper over ``io run``."""
from __future__ import annotations

import io
import sys


def _guard_streams() -> None:
    """A windowed PyInstaller build has sys.stdout / sys.stderr == None. Any
    library that touches them (uvicorn, print, logging) then crashes."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name, None) is None:
            setattr(sys, name, io.StringIO())


def main() -> None:
    _guard_streams()
    from io_assistant.cli import run

    run()


if __name__ == "__main__":
    main()
