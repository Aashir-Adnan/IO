from __future__ import annotations

import base64
import os
import secrets
import sys
import threading
import tempfile
from pathlib import Path

import httpx

from fastapi import FastAPI, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from sqlalchemy import func, select, text
from fastapi.staticfiles import StaticFiles

from io_assistant.config import Config
from io_assistant.conversation.context import format_context
from io_assistant.conversation.store import ConversationStore
from io_assistant.db import models as m
from io_assistant.db.base import make_engine, make_session_factory
from io_assistant.orchestrator import Orchestrator, PendingComplete, PendingStore
from io_assistant.service.schemas import (
    CaptionConfirmIn,
    CaptionIn,
    CaptionOut,
    ConversationOut,
    ConversationSummary,
    FileContentOut,
    FileForgetIn,
    FileForgetOut,
    FileOpenIn,
    FileRegisterIn,
    FileRegisterOut,
    FileReindexIn,
    FileReindexOut,
    FilesListOut,
    HealthOut,
    NewConversationOut,
    RecordEditIn,
    TurnResponse,
    UtteranceIn,
    VoiceHealthOut,
    VoiceOut,
)
from io_assistant.service.panels import (
    entity_panel, record_brief, records_list, standby_panel,
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
    app.state.pending: dict[str, PendingStore | PendingComplete] = {}
    app.state.recall_ms = 0

    def _run(body: UtteranceIn, on_progress=None) -> TurnResponse:
        import time

        pending = None
        if body.confirm_token:
            pending = app.state.pending.pop(body.confirm_token, None)

        conv_id = body.conversation_id or store.ensure_active()
        # A gated store replays its own text; a gated completion needs the
        # reply the user just typed ("the first one").
        text_arg = body.text or getattr(pending, "text", "")
        text_in = getattr(pending, "text", None) or body.text
        store.append(conv_id, "user", text_in, source=body.source)
        history = format_context(store.recent_turns(conv_id))

        t0 = time.perf_counter()
        if pending is not None:
            result = orchestrator.handle(text_arg, pending=pending,
                                         history=history, on_progress=on_progress)
        else:
            result = orchestrator.handle(
                body.text, source=body.source, history=history,
                on_progress=on_progress,
            )
        if result.intent == "query":
            ms = int((time.perf_counter() - t0) * 1000)
            prev = app.state.recall_ms
            app.state.recall_ms = ms if prev == 0 else (prev * 3 + ms) // 4

        msg_id = store.append(
            conv_id, "assistant", result.message,
            kind=result.intent_kind, intent=result.intent, source=body.source,
        )
        poke = getattr(getattr(app.state, "sync", None), "poke", None)
        if poke is not None:                      # sync soon after a write
            poke()

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

    @app.post("/voice/transcribe")
    def voice_transcribe(audio: UploadFile):
        """Speech-to-text only — no turn. Used by the ask bar mic and the
        media caption box. Always available when Whisper is (independent of
        the files feature)."""
        try:
            transcriber = app.state.voice.transcriber()
        except VoiceUnavailable as e:
            raise HTTPException(status_code=503, detail=e.reason)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio.file.read())
            tmp_name = tmp.name
        tr = transcriber.transcribe(tmp_name)
        if not tr.text.strip():
            raise HTTPException(status_code=422, detail="no speech")
        return {"transcript": tr.text, "confidence": tr.confidence}

    @app.get("/voice/stt")
    def voice_stt_mode():
        """Which STT the client should use: 'whisper-stream' (local real-time),
        'soniox' (cloud real-time), or 'whisper' (local batch)."""
        streaming = config.voice.stt_streaming
        if config.voice.stt_provider == "whisper-stream":
            provider = "whisper-stream"
        elif streaming:
            provider = "soniox"
        else:
            provider = "whisper"
        return {"provider": provider, "streaming": streaming}

    @app.post("/voice/stream-token")
    def voice_stream_token():
        """Mint a short-lived Soniox token so the browser can stream mic audio
        to Soniox directly — the real SONIOX_API_KEY never leaves the server."""
        from io_assistant.transcribe.soniox import SonioxUnavailable, mint_temp_key
        try:
            return mint_temp_key(config)
        except SonioxUnavailable as e:
            raise HTTPException(status_code=503, detail=e.reason)
        except httpx.HTTPError as e:
            raise HTTPException(status_code=502, detail=f"Soniox token request failed: {e}")

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

    @app.get("/entity/{etype}/{entity_id}")
    def entity(etype: str, entity_id: int):
        with factory() as s:
            panel = entity_panel(s, etype, entity_id)
        if panel is None:
            raise HTTPException(status_code=404, detail="entity not found")
        return panel

    @app.delete("/entity/{etype}/{entity_id}")
    def entity_delete(etype: str, entity_id: int):
        model = {"person": m.Person, "place": m.Place,
                 "item": m.Item, "occasion": m.Occasion}.get(etype)
        if model is None:
            raise HTTPException(status_code=400, detail="unknown entity type")
        with factory() as s:
            row = s.get(model, entity_id)
            if row is None:
                raise HTTPException(status_code=404, detail="entity not found")
            s.delete(row)      # link tables cascade
            s.commit()
        return {"deleted": {"etype": etype, "id": entity_id}}

    # --- records: browse / edit / delete (the user cleaning up bad data) ---
    @app.get("/records")
    def records_get(limit: int = 200, kind: str | None = None, domain: str | None = None):
        with factory() as s:
            return records_list(s, limit=limit, kind=kind, domain=domain)

    @app.get("/collections")
    def collections_list():
        with factory() as s:
            out = []
            for c in s.execute(select(m.Collection).order_by(m.Collection.created_at)).scalars():
                base = select(func.count()).select_from(m.Record).where(m.Record.kind == c.kind_slug)
                out.append({
                    "kind_slug": c.kind_slug, "name": c.name, "item_noun": c.item_noun,
                    "open_count": s.execute(base.where(m.Record.status == "open")).scalar_one(),
                    "done_count": s.execute(base.where(m.Record.status == "done")).scalar_one(),
                })
            return out

    @app.patch("/record/{record_id}")
    def record_edit(record_id: int, body: RecordEditIn):
        with factory() as s:
            row = s.get(m.Record, record_id)
            if row is None:
                raise HTTPException(status_code=404, detail="record not found")
            if body.title is not None and body.title.strip():
                if body.title.strip() != row.title:
                    row.title = body.title.strip()
                    try:
                        row.embedding = orchestrator._embedder.embed_one(row.title)
                    except Exception:  # noqa: BLE001
                        pass
            if body.kind is not None:
                row.kind = body.kind.strip() or row.kind
            if body.domain is not None:
                row.domain = body.domain.strip() or None
            if body.status is not None:
                # A cleared status ("") means "open" for task-kinds; `set_record_status`
                # is the one place completed_at is maintained (see tasks/complete.py).
                import datetime as _dt

                from io_assistant.tasks.complete import set_record_status
                set_record_status(s, row, body.status or "open",
                                  _dt.datetime.now(_dt.timezone.utc))
            if body.when_phrase is not None:
                import datetime as _dt
                from io_assistant.resolve.dates import ground
                res = ground(body.when_phrase or None, _dt.datetime.now(_dt.timezone.utc))
                if body.when_phrase.strip() == "":
                    row.occurred_at = row.due_at = None
                elif res.ok and res.value is not None:
                    if row.due_at and not row.occurred_at:
                        row.due_at = res.value
                    else:
                        row.occurred_at = res.value
                else:
                    raise HTTPException(status_code=422, detail=f"couldn't read the date '{body.when_phrase}'")
            s.flush()
            s.commit()
            return record_brief(s, s.get(m.Record, record_id))

    @app.delete("/record/{record_id}")
    def record_delete(record_id: int):
        with factory() as s:
            row = s.get(m.Record, record_id)
            if row is None:
                raise HTTPException(status_code=404, detail="record not found")
            s.delete(row)     # record_* link tables cascade
            s.commit()
        return {"deleted": record_id}

    @app.get("/standby")
    def standby():
        with factory() as s:
            return standby_panel(s, config, app.state.recall_ms)

    @app.post("/window/raise")
    def window_raise():
        """A second app launch calls this so the running instance surfaces its
        window (IO is desktop-only — no browser fallback). 404 when this
        process has no window (headless `io serve`)."""
        from io_assistant.service import runner

        if runner.raise_window():
            return {"raised": True}
        raise HTTPException(status_code=404, detail="no desktop window in this process")

    @app.get("/web")
    def web_smoke(q: str, kind: str = "fact"):
        """Smoke/debug endpoint for the web-answers path. 404 when [web] is off."""
        if not config.web.enabled:
            raise HTTPException(status_code=404, detail="web answers are disabled")
        if kind not in ("news", "fact"):
            raise HTTPException(status_code=400, detail="kind must be 'news' or 'fact'")
        import datetime as _dt

        from io_assistant.web.answer import WebAnswerer

        answerer = getattr(app.state, "web_answerer", None)
        if answerer is None:
            answerer = WebAnswerer(config, orchestrator._backend)
            app.state.web_answerer = answerer
        with factory() as s:
            ans = answerer.answer(s, q, kind=kind, now=_dt.datetime.now(_dt.timezone.utc))
            s.commit()
        if ans is None:
            raise HTTPException(status_code=502, detail="no web answer available")
        return {"text": ans.text, "kind": ans.kind, "tier": ans.tier,
                "sources": ans.sources, "cached": ans.cached}

    app.state.tracker_poller = None
    if config.web.enabled:
        from io_assistant.web.poller import TrackerPoller

        tp = TrackerPoller(factory, config)
        tp.start()
        app.state.tracker_poller = tp

        @app.on_event("shutdown")
        def _stop_poller():
            tp.stop()

    from io_assistant.backend.backfill import EmbeddingBackfiller

    app.state.backfiller = None
    embedder = getattr(orchestrator, "_embedder", None)
    # only when create_app owns its engine (production); tests inject theirs and
    # share one connection, which a background thread must not touch
    if engine is None and embedder is not None:
        backfiller = EmbeddingBackfiller(factory, embedder)
        backfiller.start()
        app.state.backfiller = backfiller

        @app.on_event("shutdown")
        def _stop_backfiller():
            backfiller.stop()

    from io_assistant.updates.apply import UpdateChecker, spawn_update

    updater = UpdateChecker(config)
    app.state.updater = updater
    app.state.spawn_update = spawn_update
    app.state.exit_fn = lambda: threading.Timer(1.0, os._exit, [0]).start()
    # background git fetch only in production (create_app owns its engine)
    if engine is None and config.updates.enabled:
        updater.start()

        @app.on_event("shutdown")
        def _stop_updater():
            updater.stop()

    from io_assistant.sync.manager import SyncManager

    sync = SyncManager(config, factory)
    app.state.sync = sync
    # background sync only in production (create_app owns its engine)
    if engine is None and config.sync.enabled:
        sync.start()

        @app.on_event("shutdown")
        def _stop_sync():
            sync.stop()

    @app.get("/sync")
    def sync_status():
        return app.state.sync.status()

    @app.post("/sync/now")
    def sync_now():
        return app.state.sync.sync_now()

    @app.post("/sync/signin")
    def sync_signin():
        return app.state.sync.sign_in()

    @app.post("/sync/signout")
    def sync_signout():
        app.state.sync.sign_out()
        return {"ok": True}

    @app.get("/update")
    def update_status(refresh: bool = False):
        if not config.updates.enabled:
            return {"enabled": False, "available": False}
        u = app.state.updater
        st = u.check_now() if refresh else u.status
        return {"enabled": True, "repo": u.repo is not None, **st.as_dict()}

    @app.post("/update/apply")
    def update_apply():
        u = app.state.updater
        st = u.status
        if not config.updates.enabled or u.repo is None:
            raise HTTPException(status_code=409, detail="Updates aren't available: no git checkout found.")
        if not st.available:
            raise HTTPException(status_code=409, detail="IO is already up to date.")
        if st.dirty:
            raise HTTPException(
                status_code=409,
                detail="You have local changes to tracked files. Commit or discard them, then try again.")
        app.state.spawn_update(u.repo, "exe" if getattr(sys, "frozen", False) else "dev")
        app.state.exit_fn()
        return {"ok": True}

    app.state.index_queue = None
    if config.files.enabled:
        from io_assistant.files.paths import AccessDenied, AccessGate
        from io_assistant.files.store import FileIndex
        from io_assistant.files.index import FileIndexer
        from io_assistant.files.queue import IndexQueue
        from io_assistant.files.extract import read_document

        gate = AccessGate(config.files)
        file_index = FileIndex(factory)
        indexer = FileIndexer(
            orchestrator._embedder, orchestrator._backend,
            config.files, config.resolver,
        )
        iq = IndexQueue(factory, indexer, gate)
        iq.start()
        app.state.index_queue = iq
        orchestrator._index_queue = iq   # so _file_open defers indexing too

        @app.on_event("shutdown")
        def _stop_queue():
            iq.stop()

        @app.post("/files", response_model=FileRegisterOut)
        def files_register(body: FileRegisterIn):
            with factory() as s:
                try:
                    target = gate.resolve(body.path)
                    res = file_index.register(s, target, gate, config.files)
                    s.commit()
                except AccessDenied as e:
                    raise HTTPException(status_code=400, detail=e.reason)
                iq.enqueue_many(n.path for n in file_index.stale(s))
            return FileRegisterOut(root=str(target), discovered=res.discovered,
                                   skipped=res.skipped)

        @app.get("/files", response_model=FilesListOut)
        def files_list():
            with factory() as s:
                return FilesListOut(
                    enabled=True, roots=file_index.status_summary(s)["roots"])

        @app.delete("/files", response_model=FileForgetOut)
        def files_forget(body: FileForgetIn):
            with factory() as s:
                n = file_index.forget(s, gate.key(gate.resolve(body.path)))
                s.commit()
            return FileForgetOut(forgotten=n)

        @app.post("/files/reindex", response_model=FileReindexOut)
        def files_reindex(body: FileReindexIn):
            with factory() as s:
                paths = [n.path for n in file_index.stale(s)]
            iq.enqueue_many(paths)
            return FileReindexOut(queued=len(paths))

        @app.get("/files/status")
        def files_status():
            with factory() as s:
                d = file_index.status_summary(s)
            d["queue_depth"] = iq.depth()
            return d

        @app.get("/files/content", response_model=FileContentOut)
        def files_content(path: str):
            p = gate.resolve(path)
            with factory() as s:
                try:
                    gate.assert_allowed(
                        p, registered_keys=file_index.authorized_keys(s))
                except AccessDenied as e:
                    raise HTTPException(status_code=400, detail=e.reason)
            doc = read_document(p, config.files)
            if doc.status != "ok":
                raise HTTPException(status_code=404, detail=doc.status)
            return FileContentOut(path=str(p), title=doc.title, text=doc.text[:20000])

        # --- media (Phase 2C) ------------------------------------------
        import datetime as _dt

        from io_assistant.files.caption import PendingCaption, apply_caption
        from io_assistant.files.command import resolve_folder
        from io_assistant.files.gallery import open_folder as _open_folder
        from io_assistant.files.thumbs import make_thumb

        app.state.caption_pending: dict[str, PendingCaption] = {}

        def _assert_allowed(p):
            with factory() as s:
                gate.assert_allowed(
                    p, registered_keys=file_index.authorized_keys(s))

        @app.get("/files/raw")
        def files_raw(path: str):
            p = gate.resolve(path)
            try:
                _assert_allowed(p)
            except AccessDenied as e:
                raise HTTPException(status_code=400, detail=e.reason)
            if not p.is_file():
                raise HTTPException(status_code=404, detail="not found")
            return FileResponse(str(p))

        @app.get("/files/thumb")
        def files_thumb(path: str):
            p = gate.resolve(path)
            try:
                _assert_allowed(p)
            except AccessDenied as e:
                raise HTTPException(status_code=400, detail=e.reason)
            with factory() as s:
                node = file_index.get(s, gate.key(p))
                tp = node.thumb_path if node else None
                if tp and Path(tp).is_file():
                    return FileResponse(tp, media_type="image/webp")
                import os as _os

                made = make_thumb(
                    p, (node.media_kind if node else None) or "image",
                    Path(_os.path.expanduser(config.files.thumbs_dir)),
                    path_key=gate.key(p))
                if made is None:
                    raise HTTPException(status_code=404, detail="no thumbnail")
                # persist so this generate-on-miss happens exactly once
                if node is not None:
                    node.thumb_path = str(made)
                    s.commit()
            return FileResponse(str(made), media_type="image/webp")

        @app.post("/files/open")
        def files_open(body: FileOpenIn):
            with factory() as s:
                if body.path:
                    target = gate.resolve(body.path)
                else:
                    res = resolve_folder(body.phrase or "", s, gate, config.files)
                    if res.kind == "many":
                        raise HTTPException(status_code=409, detail={
                            "candidates": [pp.name for pp in res.candidates]})
                    if res.kind == "none":
                        raise HTTPException(status_code=404,
                                            detail="folder not found")
                    target = res.path
                try:
                    card = _open_folder(s, target, gate=gate,
                                        index=file_index, config=config.files,
                                        index_queue=app.state.index_queue)
                    s.commit()
                except AccessDenied as e:
                    raise HTTPException(status_code=400, detail=e.reason)
            return card.model_dump(mode="json")

        def _caption_out(res, token=None) -> CaptionOut:
            return CaptionOut(
                caption=res.caption,
                entities=[e.model_dump() for e in res.entities],
                gated=res.gated, reasons=res.gate_reasons, pending_token=token)

        @app.post("/files/caption", response_model=CaptionOut)
        def files_caption(body: CaptionIn):
            with factory() as s:
                try:
                    res = apply_caption(
                        s, gate.resolve(body.path), body.text, body.source,
                        gate=gate, index=file_index,
                        backend=orchestrator._backend,
                        embedder=orchestrator._embedder,
                        resolver_cfg=config.resolver,
                        owner_name=config.owner_name,
                        now=_dt.datetime.now(_dt.timezone.utc))
                except AccessDenied as e:
                    raise HTTPException(status_code=400, detail=e.reason)
                if res.gated:
                    tok = secrets.token_urlsafe(8)
                    app.state.caption_pending[tok] = res.pending
                    return _caption_out(res, tok)
                s.commit()
            return _caption_out(res)

        @app.post("/files/caption/confirm", response_model=CaptionOut)
        def files_caption_confirm(body: CaptionConfirmIn):
            pending = app.state.caption_pending.pop(body.pending_token, None)
            if pending is None:
                raise HTTPException(status_code=404, detail="unknown token")
            with factory() as s:
                res = apply_caption(
                    s, Path(pending.path), pending.text, pending.source,
                    gate=gate, index=file_index, backend=orchestrator._backend,
                    embedder=orchestrator._embedder,
                    resolver_cfg=config.resolver,
                    owner_name=config.owner_name,
                    now=_dt.datetime.now(_dt.timezone.utc),
                    confirmed=True, extraction=pending.extraction)
                s.commit()
            return _caption_out(res)

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        import asyncio
        import queue as _queue

        await sock.accept()
        try:
            while True:
                raw = await sock.receive_text()
                try:
                    body = UtteranceIn.model_validate_json(raw)
                except Exception as e:
                    await sock.send_json({"type": "error", "message": str(e)})
                    continue

                evq: _queue.Queue = _queue.Queue()
                task = asyncio.create_task(
                    asyncio.to_thread(_run, body,
                                      lambda s, d: evq.put_nowait((s, d)))
                )
                while True:
                    try:
                        stage, detail = evq.get_nowait()
                        await sock.send_json({"type": "progress",
                                              "stage": stage, "detail": detail})
                        continue
                    except _queue.Empty:
                        pass
                    if task.done():
                        break
                    await asyncio.sleep(0.05)
                while not evq.empty():
                    stage, detail = evq.get_nowait()
                    await sock.send_json({"type": "progress",
                                          "stage": stage, "detail": detail})
                turn = task.result()
                await sock.send_json({"type": "answer", **turn.model_dump()})
        except WebSocketDisconnect:
            return

    @app.websocket("/ws/transcribe")
    async def ws_transcribe(sock: WebSocket):
        """Local real-time STT. Client streams 16 kHz mono PCM16 as binary
        frames; a text frame '{"type":"end"}' (or disconnect) finishes.
        Server pushes {"type":"partial","text":...} as words firm up and one
        {"type":"final","text":...} at the end."""
        import asyncio

        await sock.accept()
        if config.voice.stt_provider != "whisper-stream":
            await sock.send_json({"type": "error", "message": "voice.stt_provider is not 'whisper-stream'"})
            await sock.close()
            return
        try:
            session = app.state.voice.streamer().session()
        except VoiceUnavailable as e:
            await sock.send_json({"type": "error", "message": e.reason})
            await sock.close()
            return

        async def emit_partials():
            while True:
                await asyncio.sleep(0.4)
                try:
                    text = await asyncio.to_thread(session.poll)
                except Exception as e:  # noqa: BLE001
                    await sock.send_json({"type": "error", "message": str(e)})
                    return
                if text:
                    await sock.send_json({"type": "partial", "text": text})

        pump = asyncio.create_task(emit_partials())
        try:
            while True:
                msg = await sock.receive()
                if msg.get("type") == "websocket.disconnect":
                    break
                if (b := msg.get("bytes")) is not None:
                    session.feed(b)
                elif (t := msg.get("text")) is not None and '"end"' in t:
                    break
        except WebSocketDisconnect:
            pass
        finally:
            pump.cancel()
        try:
            final = await asyncio.to_thread(session.finish)
            await sock.send_json({"type": "final", "text": final})
        except Exception:  # noqa: BLE001
            pass
        await sock.close()

    frontend = (
        Path(config.service.frontend_dir)
        if config.service.frontend_dir
        else Path(__file__).resolve().parents[2] / "frontend"
    )
    if frontend.is_dir():
        class _NoCacheStatic(StaticFiles):
            # local-first desktop app: assets must always reflect the current
            # build, never a stale browser cache.
            def is_not_modified(self, response_headers, request_headers):
                return False

            async def get_response(self, path, scope):
                resp = await super().get_response(path, scope)
                for h in ("etag", "last-modified"):
                    if h in resp.headers:
                        del resp.headers[h]
                resp.headers["cache-control"] = "no-store, must-revalidate"
                resp.headers["pragma"] = "no-cache"
                return resp

        app.mount(
            "/app",
            _NoCacheStatic(directory=str(frontend), html=True),
            name="frontend",
        )

    return app
