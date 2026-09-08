# Desktop app + local service (Plan 3, 2026-09-08)

The Orchestrator runs behind a local FastAPI service. `io serve` is headless;
`io run` also opens a `pywebview` window.

## Service — `io_assistant/service/`

- `app.py` — `create_app(config, *, orchestrator=None, engine=None) -> FastAPI`.
  Builds (or accepts, for tests) exactly one engine + `sessionmaker` +
  `Orchestrator`, stashed on `app.state`. `Orchestrator.handle` owns a session
  per call, so the service never holds one between requests.
  - `GET /` → `{"service": "io", "status": "ok"}`
  - `GET /health` → `{ok, database, backend_provider}` (`SELECT 1` probe)
  - `POST /utterance` — `{text, source, confirm_token?}` → `{intent, message,
    pending_token?, stored}`. The confirmation gate is carried across calls in
    `app.state.pending: dict[token, PendingStore]` (in-memory, single-user).
    Reply "yes" with the returned `pending_token` to confirm.
  - `WS /ws` — same logic; client sends `UtteranceIn` JSON frames, server
    replies `{"type": "answer", ...}` or `{"type": "error", "message": ...}`.
    One frame per answer — token streaming is deferred.
- `runner.py` — `run_service(config, *, block=True)` (uvicorn; `block=False`
  returns `(server, thread)` after `/health` goes green) and `open_window(url)`
  (lazy `import webview`; raises a clear RuntimeError with a browser fallback if
  pywebview is unavailable).
- `schemas.py` — `UtteranceIn` / `UtteranceOut` / `HealthOut`.

## Frontend — `frontend/` (served at `/app`)

Vendored static ES modules, no build step, **no CDN** (local-first —
`tests/test_frontend_assets.py` fails on any non-local `http(s)://`).
- `app.js` — hash router (`#/chat` active; `#/timeline` `#/sources` `#/review`
  stubbed), WS client with auto-reconnect, `store.transcript`, `send()`.
- `components/message.js` — `renderMessage(role, text, shape)`; markdown via
  `vendor/markdown.js` (hand-rolled: headings/lists/bold/italic/code/fences/
  links; a ```mermaid fence renders as a labelled `<pre>` — real Mermaid
  rendering needs a deliberate vendored lib, tracked in backlog).

## Conversation layer (Phase 1.5)

- `io_assistant/conversation/` — `ConversationStore` (CRUD on the
  `conversations` / `messages` tables from migration `0003`) + `format_context`
  (recent turns → a capped `you:` / `io:` string). The **service** owns the
  tables; `Orchestrator` never touches them (the CLI passes `history=None`).
- Per turn (`/utterance`, `/voice`, `/ws`): `ensure_active()` → append the user
  message → `format_context(recent_turns())` → `orchestrator.handle(text,
  history=…)` → append the assistant message.
- `Backend` gains `context=` on `route`/`plan`/`phrase` and a new
  `acknowledge(facts, context=)` — the STORE reply is a natural sentence, not a
  template. `acknowledge` may only restate `build_fact_list()` output (rows
  `persist_store` wrote) — LLM boundary intact.
- Every turn endpoint returns **`TurnResponse`**: `kind` (answer|ack|gate|
  unknown|error), `intent`, `text`, `shape`, `cards`, `pending_token`,
  `conversation_id`, `message_id`, `audio_b64`. `cards` are `record` /
  `tasklist` / `sources` (`orchestrator_cards.py`).
- `GET /conversation(s)`, `POST /conversation`; `GET /entity/{etype}/{id}` (the
  Memory Inspector — deterministic facts + confidence from vector similarity);
  `GET /standby` (greeting name, `memories`/`recall_ms`/`clock`, surfaced chips).

## Voice in the service (Phase 1.5)

- `POST /voice` — multipart WAV in → `WhisperTranscriber` → the same turn flow →
  `PiperSpeaker.synthesize` → `VoiceOut` (`TurnResponse` + `transcript` +
  `audio_b64`). `GET /voice/health`. `service/voice.py:VoiceModels` builds
  Whisper/Piper lazily on the first `/voice` hit; `503` with a reason when a
  model is missing.
- `PiperSpeaker` now synthesises **sentence by sentence** with inter-sentence
  silence and a tuned `SynthesisConfig` (`speak/speech_text.py` does the text
  prep — abbreviations, times, pauses). Default voice `en_US-hfc_female-medium`.
- `io listen` is a thin client of `POST /voice` (`voice/client.py:ServiceClient`
  + `voice/loop.py:VoiceLoop`) — capture stays local, transcribe + synth are the
  server.

## Deferred

State 1d task runner (agent loop); external-source provenance; entity-file
browser; token streaming over `/ws`; real Mermaid; Kokoro `Speaker` adapter.
