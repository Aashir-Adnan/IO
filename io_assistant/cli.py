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
    from io_assistant.service.bootstrap import BootstrapError, ensure_database
    from io_assistant.service.runner import run_service

    config = load_config()
    try:
        ensure_database(config)
    except BootstrapError as e:
        print(e.message)
        raise typer.Exit(1)
    print(f"io service on http://{config.service.host}:{config.service.port}")
    run_service(config, block=True)


@app.command()
def run() -> None:
    """Open the desktop window, starting the service only if one isn't up."""
    import httpx

    from io_assistant.service.runner import open_window, run_service
    from io_assistant.service.singleton import (
        acquire_single_instance, surface_running_instance)

    config = load_config()
    inst = acquire_single_instance()
    if inst is None:
        surface_running_instance(config)
        raise SystemExit(0)

    from io_assistant.service.bootstrap import BootstrapError, ensure_database
    try:
        ensure_database(config)
    except BootstrapError as e:
        from io_assistant.service.runner import error_dialog

        error_dialog(e.message)
        raise SystemExit(1)

    with inst:
        base = f"http://{config.service.host}:{config.service.port}"
        url = f"{base}/app/"

        try:
            already = bool(httpx.get(f"{base}/health", timeout=1).json().get("ok"))
        except Exception:
            already = False

        fs = config.ui.fullscreen
        if already:
            open_window(url, fullscreen=fs)
            return

        server, _thread = run_service(config, block=False)
        try:
            open_window(url, fullscreen=fs)
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


files_app = typer.Typer(help="register and search local files")
app.add_typer(files_app, name="files")


def _files_ctx():
    config = load_config()
    if not config.files.enabled:
        typer.echo("Files are disabled. Set [files].enabled = true in config.toml.")
        raise typer.Exit(1)
    engine = make_engine(config.database_url)
    factory = make_session_factory(engine)
    from io_assistant.backend.factory import build_backend
    from io_assistant.backend.embed import Embedder
    from io_assistant.files.paths import AccessGate
    from io_assistant.files.store import FileIndex
    from io_assistant.files.index import FileIndexer

    backend = build_backend(config)
    embedder = Embedder(config)
    return (
        config, engine, factory, AccessGate(config.files),
        FileIndex(factory),
        FileIndexer(embedder, backend, config.files, config.resolver),
        backend, embedder,
    )


@files_app.command("add")
def files_add(path: str, no_index: bool = typer.Option(False, "--no-index")):
    """Register a file or folder and index it."""
    config, engine, factory, gate, index, indexer, backend, embedder = _files_ctx()
    if config.backend.provider != "local":
        typer.echo("Note: file text will be sent to api.anthropic.com "
                   "(backend.provider is not 'local').")
    from pathlib import Path
    try:
        with factory() as s:
            target = gate.resolve(path)
            res = index.register(s, target, gate, config.files)
            s.commit()
            typer.echo(f"registered {target} — {res.discovered} file(s)")
            if not no_index:
                for node in index.stale(s):
                    indexer.index_path(s, Path(node.path), gate=gate)
                s.commit()
                typer.echo("indexed.")
    finally:
        engine.dispose()


@files_app.command("list")
def files_list():
    """List registered roots."""
    config, engine, factory, gate, index, *_ = _files_ctx()
    try:
        with factory() as s:
            for r in index.roots(s):
                typer.echo(f"{r.kind:4} {r.path}")
    finally:
        engine.dispose()


@files_app.command("reindex")
def files_reindex(
    path: str = typer.Argument(None),
    all_stale: bool = typer.Option(False, "--all-stale"),
):
    """Re-index stale files."""
    config, engine, factory, gate, index, indexer, *_ = _files_ctx()
    from pathlib import Path
    try:
        with factory() as s:
            for node in index.stale(s):
                indexer.index_path(s, Path(node.path), gate=gate, force=bool(path))
            s.commit()
        typer.echo("reindexed stale files.")
    finally:
        engine.dispose()


@files_app.command("forget")
def files_forget(path: str):
    """Unregister a path from the index (files on disk are untouched)."""
    config, engine, factory, gate, index, *_ = _files_ctx()
    typer.confirm(f"Unregister {path} from the index?", abort=True)
    try:
        with factory() as s:
            n = index.forget(s, gate.key(gate.resolve(path)))
            s.commit()
        typer.echo(f"forgot {n} node(s).")
    finally:
        engine.dispose()


@files_app.command("search")
def files_search(query: list[str]):
    """Search indexed files and print the answer."""
    import datetime as dt

    config, engine, factory, gate, index, indexer, backend, embedder = _files_ctx()
    from io_assistant.files.search import FileSearcher

    q = " ".join(query)
    try:
        with factory() as s:
            ans = FileSearcher(
                embedder, backend, config.files, config.resolver
            ).search(s, q, dt.datetime.now(dt.timezone.utc), gate=gate)
            s.commit()
        typer.echo(ans.text)
        for h in ans.hits:
            typer.echo(f"  - {h.path}  ({h.why})")
    finally:
        engine.dispose()


@files_app.command("status")
def files_status():
    """Show index counts."""
    config, engine, factory, gate, index, *_ = _files_ctx()
    try:
        with factory() as s:
            d = index.status_summary(s)
        typer.echo(
            f"{d['indexed']}/{d['total']} indexed, {d['stale']} stale, "
            f"{d['errors']} errors"
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    app()
