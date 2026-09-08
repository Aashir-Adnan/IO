from __future__ import annotations

import typer

from io_assistant.config import load_config
from io_assistant.db.base import make_engine, make_session_factory
from io_assistant.orchestrator import Orchestrator, PendingStore

app = typer.Typer(help="io — personal knowledge assistant")


@app.command()
def store(text: str) -> None:
    """Store an utterance."""
    config = load_config()
    engine = make_engine(config.database_url)
    factory = make_session_factory(engine)
    try:
        res = Orchestrator(config, session_factory=factory).handle(text)
    finally:
        engine.dispose()
    print(res.message)


@app.command()
def repl() -> None:
    """Interactive loop."""
    config = load_config()
    engine = make_engine(config.database_url)
    factory = make_session_factory(engine)
    orch = Orchestrator(config, session_factory=factory)
    # A gated store held verbatim (utterance id + extraction) for replay.
    pending_store: PendingStore | None = None
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

            is_confirm = pending_store is not None and stripped.lower() in {"y", "yes"}

            if is_confirm:
                # Replay the held extraction — no re-route, no re-extract,
                # no second utterance row.
                res = orch.handle(pending_store.text, pending=pending_store)
            else:
                res = orch.handle(stripped)

            print(res.message)
            pending_store = res.pending
    finally:
        engine.dispose()


@app.command()
def serve() -> None:
    """Run the local FastAPI service (no window)."""
    from io_assistant.service.runner import run_service

    config = load_config()
    print(f"io service on http://{config.service.host}:{config.service.port}")
    run_service(config, block=True)


@app.command()
def run() -> None:
    """Start the service and open the desktop window."""
    from io_assistant.service.runner import open_window, run_service

    config = load_config()
    server, _thread = run_service(config, block=False)
    url = f"http://{config.service.host}:{config.service.port}/app/"
    try:
        open_window(url)
    finally:
        server.should_exit = True


@app.command()
def doctor() -> None:
    """Environment diagnostics (Plan 4)."""
    print("io doctor: not implemented yet (Plan 4)")
    raise typer.Exit(0)


if __name__ == "__main__":
    app()
