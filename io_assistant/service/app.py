from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from io_assistant.config import Config
from io_assistant.db.base import make_engine, make_session_factory
from io_assistant.orchestrator import Orchestrator, PendingStore
from io_assistant.service.schemas import HealthOut, UtteranceIn, UtteranceOut

__all__ = ["create_app"]


def create_app(config: Config, *, orchestrator=None, engine=None) -> FastAPI:
    app = FastAPI(title="io", version="0.1.0")

    eng = engine if engine is not None else make_engine(config.database_url)
    if orchestrator is None:
        factory = make_session_factory(eng)
        orchestrator = Orchestrator(config, session_factory=factory)

    app.state.config = config
    app.state.engine = eng
    app.state.orchestrator = orchestrator
    app.state.pending: dict[str, PendingStore] = {}

    def _run(body: UtteranceIn) -> UtteranceOut:
        pending = None
        if body.confirm_token:
            pending = app.state.pending.pop(body.confirm_token, None)
        if pending is not None:
            result = orchestrator.handle(pending.text, pending=pending)
        else:
            result = orchestrator.handle(body.text, source=body.source)

        token = None
        if result.pending is not None:
            token = secrets.token_urlsafe(8)
            app.state.pending[token] = result.pending
        stored = result.stored is not None and not getattr(
            result.stored, "gated", False
        )
        return UtteranceOut(
            intent=result.intent,
            message=result.message,
            pending_token=token,
            stored=stored,
        )

    @app.get("/")
    def root():
        return {"service": "io", "status": "ok"}

    @app.get("/health", response_model=HealthOut)
    def health():
        db_ok = True
        try:
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception:
            db_ok = False
        return HealthOut(
            ok=db_ok,
            database=db_ok,
            backend_provider=config.backend.provider,
        )

    @app.post("/utterance", response_model=UtteranceOut)
    def utterance(body: UtteranceIn):
        return _run(body)

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        try:
            while True:
                raw = await sock.receive_text()
                try:
                    body = UtteranceIn.model_validate_json(raw)
                except Exception as e:
                    await sock.send_json({"type": "error", "message": str(e)})
                    continue
                out = _run(body)
                await sock.send_json({"type": "answer", **out.model_dump()})
        except WebSocketDisconnect:
            return

    frontend = (
        Path(config.service.frontend_dir)
        if config.service.frontend_dir
        else Path(__file__).resolve().parents[2] / "frontend"
    )
    if frontend.is_dir():
        app.mount(
            "/app",
            StaticFiles(directory=str(frontend), html=True),
            name="frontend",
        )

    return app
