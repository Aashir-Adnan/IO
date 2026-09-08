from __future__ import annotations

import typer

from io_assistant._env import load_env_once
from io_assistant.config import load_config

load_env_once()  # pick up repo-root .env before any command reads os.environ
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
    """Open the desktop window, starting the service only if one isn't up."""
    import httpx

    from io_assistant.service.runner import open_window, run_service

    config = load_config()
    base = f"http://{config.service.host}:{config.service.port}"
    url = f"{base}/app/"

    try:
        already = bool(httpx.get(f"{base}/health", timeout=1).json().get("ok"))
    except Exception:
        already = False

    if already:
        open_window(url)
        return

    server, _thread = run_service(config, block=False)
    try:
        open_window(url)
    finally:
        server.should_exit = True


@app.command()
def listen(passive: bool = typer.Option(None, help="hands-free VAD mode")) -> None:
    """Voice: speak to io, hear the answer."""
    from io_assistant.voice.client import ServiceClient
    from io_assistant.voice.loop import VoiceLoop

    config = load_config()
    base = f"http://{config.service.host}:{config.service.port}"
    client = ServiceClient(base)
    if not client.health():
        print(f"io service not reachable at {base} — run `io serve` first.")
        raise typer.Exit(1)
    vh = client.voice_health()
    if not (vh.get("whisper") and vh.get("piper")):
        print(f"voice not ready: {vh.get('reason')}")
        raise typer.Exit(1)
    loop = VoiceLoop(config, client=client)
    use_passive = config.capture.passive if passive is None else passive
    (loop.run_passive if use_passive else loop.run_push_to_talk)()


@app.command()
def doctor() -> None:
    """Check the local stack (Postgres, pgvector, models, Whisper, Piper)."""
    from io_assistant.doctor import format_report, run_checks

    checks = run_checks(load_config())
    print(format_report(checks))
    raise typer.Exit(0 if all(c.ok for c in checks) else 1)


if __name__ == "__main__":
    app()
