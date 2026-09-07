from __future__ import annotations

import typer

from io_assistant.config import load_config
from io_assistant.db.base import make_engine, make_session_factory
from io_assistant.orchestrator import Orchestrator

app = typer.Typer(help="io — personal knowledge assistant")


def _make_session_factory(config):
    engine = make_engine(config.database_url)
    return engine, make_session_factory(engine)


@app.command()
def store(text: str) -> None:
    """Store an utterance."""
    config = load_config()
    engine, factory = _make_session_factory(config)
    session = factory()
    orch = Orchestrator(config, session_factory=lambda: session)
    try:
        res = orch.handle(text)
        session.commit()
    finally:
        session.close()
        engine.dispose()
    print(res.message)


@app.command()
def repl() -> None:
    """Interactive loop."""
    config = load_config()
    engine, factory = _make_session_factory(config)
    pending_text: str | None = None  # text of a gated store awaiting confirmation
    try:
        while True:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            stripped = line.strip()
            if stripped.lower() in {"exit", "quit"}:
                break
            if not stripped:
                continue

            is_confirm = pending_text is not None and stripped.lower() in {"y", "yes"}
            text = pending_text if is_confirm else line

            session = factory()
            try:
                orch = Orchestrator(config, session_factory=lambda s=session: s)
                res = orch.handle(text, confirmed=is_confirm)
                session.commit()
            finally:
                session.close()

            print(res.message)
            if res.stored is not None and res.stored.gated:
                pending_text = text
            else:
                pending_text = None
    finally:
        engine.dispose()


@app.command()
def doctor() -> None:
    """Environment diagnostics (Plan 4)."""
    print("io doctor: not implemented yet (Plan 4)")
    raise typer.Exit(0)


if __name__ == "__main__":
    app()
