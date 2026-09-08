"""Frozen-app entry point (PyInstaller). Thin wrapper over ``io run``."""
from __future__ import annotations


def main() -> None:
    from io_assistant.cli import run

    run()


if __name__ == "__main__":
    main()
