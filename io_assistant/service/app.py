from __future__ import annotations

import base64
import secrets
import tempfile
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from sqlalchemy import text
from fastapi.staticfiles import StaticFiles

from io_assistant.config import Config
from io_assistant.conversation.context import format_context
from io_assistant.conversation.store import ConversationStore
from io_assistant.db.base import make_engine, make_session_factory
from io_assistant.orchestrator import Orchestrator, PendingStore
from io_assistant.service.schemas import (
    ConversationOut,
    ConversationSummary,
    HealthOut,
    NewConversationOut,
    TurnResponse,
    UtteranceIn,
    VoiceHealthOut,
    VoiceOut,
)
from io_assistant.service.voice import VoiceModels, VoiceUnavailable

__all__ = ["create_app"]


def create_app(
    config: Config,
    *,
    orchestrator=None,
    engine=None,
    conversations: ConversationStore | None = None,
    voice=None,
) -> FastAPI:
    app = FastAPI(title="io", version="0.1.0")

    eng = engine if engine is not None else make_engine(config.database_url)
    factory = make_session_factory(eng)
    if orchestrator is None:
        orchestrator = Orchestrator(config, session_factory=factory)
    store = conversations or ConversationStore(factory)

    app.state.config = config
    app.state.engine = eng
    app.state.orchestrator = orchestrator
    app.state.conversations = store
    app.state.voice = voice or VoiceModels(config)
    app.state.pending: dict[str, PendingStore] = {}
    app.state.recall_ms = 0

    def _run(body: UtteranceIn) -> TurnResponse:
        pending = None
        if body.confirm_token:
            pending = app.state.pending.pop(body.confirm_token, None)

        conv_id = body.conversation_id or store.ensure_active()
        text_in = pending.text if pending is not None else body.text
        store.append(conv_id, "user", text_in, source=body.source)
        history = format_context(store.recent_turns(conv_id))

        if pending is not None:
            result = orchestrator.handle(pending.text, pending=pending, history=history)
        else:
            result = orchestrator.handle(
                body.text, source=body.source, history=history
            )

        msg_id = store.append(
            conv_id, "assistant", result.message,
            kind=result.intent_kind, intent=result.intent, source=body.source,
        )

        token = None
        if result.pending is not None:
            token = secrets.token_urlsafe(8)
            app.state.pending[token] = result.pending

        return TurnResponse(
            kind=result.intent_kind,
            intent=result.intent,
            text=result.message,
            shape=result.shape,
            cards=[c.model_dump(mode="json") for c in result.cards],
            pending_token=token,
            conversation_id=conv_id,
            message_id=msg_id,
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
            ok=db_ok, database=db_ok, backend_provider=config.backend.provider
        )

    @app.post("/utterance", response_model=TurnResponse)
    def utterance(body: UtteranceIn):
        return _run(body)

    @app.get("/voice/health", response_model=VoiceHealthOut)
    def voice_health():
        return app.state.voice.health()

    @app.post("/voice", response_model=VoiceOut)
    def voice_turn(
        audio: UploadFile,
        conversation_id: int | None = Form(None),
        speak: str = Form("1"),
    ):
        try:
            transcriber = app.state.voice.transcriber()
        except VoiceUnavailable as e:
            raise HTTPException(status_code=503, detail=e.reason)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio.file.read())
            path = tmp.name
        tr = transcriber.transcribe(path)
        if not tr.text.strip():
            raise HTTPException(status_code=422, detail="no speech")

        turn = _run(UtteranceIn(
            text=tr.text, source="voice", conversation_id=conversation_id
        ))

        audio_b64 = None
        if speak == "1" and turn.kind not in ("error",):
            try:
                data = app.state.voice.speaker().synthesize(turn.text)
                audio_b64 = base64.b64encode(data).decode("ascii")
            except VoiceUnavailable:
                audio_b64 = None

        data = turn.model_dump()
        data["audio_b64"] = audio_b64
        return VoiceOut(
            **data,
            transcript=tr.text,
            transcript_confidence=tr.confidence,
        )

    @app.get("/conversations", response_model=list[ConversationSummary])
    def conversations_list():
        return store.list_conversations()

    @app.post("/conversation", response_model=NewConversationOut)
    def conversation_new():
        return NewConversationOut(conversation_id=store.create())

    @app.get("/conversation", response_model=ConversationOut)
    def conversation_get(id: int | None = None, before: int | None = None):
        cid = id or store.active_id()
        if cid is None:
            cid = store.create()
        return ConversationOut(
            conversation_id=cid,
            messages=store.history(cid, before_id=before),
        )

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
                turn = _run(body)
                await sock.send_json({"type": "answer", **turn.model_dump()})
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
