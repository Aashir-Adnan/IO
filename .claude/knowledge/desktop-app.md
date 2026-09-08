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

## Deferred

Token streaming over `/ws`; real Mermaid; `orchestrator.handle` off the event
loop; a `GET /utterances` history endpoint.
