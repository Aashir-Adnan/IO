# IO Phase 3 — Local Service + Desktop Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the Orchestrator as a local FastAPI service (REST + WebSocket) and open a `pywebview` desktop window whose chat view drives it — so typed, GUI, and (Plan 4) voice input all share one code path. `io run` starts both; `io serve` starts the service alone for headless clients.

**Architecture:** A thin service layer (`io_assistant/service/`) wraps the existing `Orchestrator` — one engine, one `sessionmaker`, one `Orchestrator` per process. REST `POST /utterance` runs `handle()` and returns the answer; the confirmation gate is carried across calls with an in-memory pending-token map (single-user, single-process). A WebSocket mirrors `POST /utterance` for the GUI and future unprompted pushes. The frontend is vendored static files served by FastAPI and loaded into a `pywebview` window; a hand-rolled Markdown renderer keeps the local-first rule (no CDN, no bundled megabyte libs).

**Tech Stack:** Python 3.11+, `uv`, FastAPI + `uvicorn`, `pywebview`, `httpx` (test client), SQLAlchemy 2.x. New deps: `fastapi`, `uvicorn[standard]`, `pywebview`.

**Spec:** `docs/superpowers/specs/2026-09-07-io-phase-1-design.md` §6 (capture/typed), §7 (desktop app — primary reference), §8 (tech stack). `.claude/knowledge/` — add `desktop-app.md`.

## Global Constraints

- **Python** ≥ 3.11. Everything through `uv`.
- **Local-first (hard rule):** the service binds `127.0.0.1` only. The frontend
  references **zero** external URLs — every script, style, and font is a file in
  `frontend/`. No CDN, no `<script src="https://...">`. `tests/test_e2e_store.py`'s
  socket guard still governs the pipeline; a new `tests/test_frontend_assets.py`
  greps the frontend for `http://`/`https://` and fails on a hit (localhost
  excepted).
- **LLM boundary:** unchanged — the service adds transport, not intelligence.
- **One process, one Orchestrator:** `create_app` builds exactly one engine +
  `sessionmaker` + `Orchestrator`; `Orchestrator.handle` already owns a session
  per call (Plan-1 cleanup). The service never holds a session between requests.
- **TDD:** failing test first. FastAPI routes are tested with
  `fastapi.testclient.TestClient` against a real DB (`IO_TEST_DATABASE_URL`) and
  a `FakeBackend`. The GUI (`pywebview`, `app.js`) is verified by (a) an asset
  lint test, (b) a static structure test, (c) a manual smoke recorded in the
  task. No headless browser is assumed.
- Tests need `IO_TEST_DATABASE_URL` exported. DB is docker compose Postgres+pgvector on `:5432`.

---

## File Structure

```
io_assistant/
  service/
    __init__.py
    app.py          # create_app(config) -> FastAPI; routes; pending-token map
    schemas.py      # pydantic request/response models
    runner.py       # run_service() (uvicorn) and open_window() (pywebview)
  cli.py            # add `serve` and `run` commands
frontend/
  index.html
  app.js            # hash router, WS client, shared state
  styles/app.css
  vendor/
    markdown.js     # hand-rolled minimal Markdown -> HTML (no dependency)
  views/
    chat.js         # [ACTIVE] transcript + input + status line
    timeline.js     # [STUB]
    sources.js      # [STUB]
    review.js       # [STUB]
  components/
    message.js      # renderMessage(): text | markdown | ```mermaid fence
tests/
  test_service_health.py
  test_service_utterance.py
  test_service_ws.py
  test_service_e2e.py        # scenarios 1 & 2 over HTTP
  test_frontend_assets.py    # local-first asset lint + structure
```

---

## Task 1: Dependencies + `[service]` config

**Files:**
- Modify: `pyproject.toml`, `config.toml`, `io_assistant/config.py`, `tests/conftest.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `pyproject.toml` deps gain `fastapi>=0.110`, `uvicorn[standard]>=0.29`,
    `pywebview>=5.0`; dev deps gain `httpx>=0.27` (already a runtime dep — leave)
    — no, `httpx` is already there.
  - `ServiceConfig` (pydantic `BaseModel`): `host: str = "127.0.0.1"`,
    `port: int = 8765`, `frontend_dir: str | None = None` (None → the repo's
    `frontend/`).
  - `Config.service: ServiceConfig` — new nested section, optional in the TOML
    (defaults apply when `[service]` is absent).
  - `config` fixture in `conftest.py` gains `service=ServiceConfig()`.

- [ ] **Step 1: Add deps**

`pyproject.toml` `dependencies`: add
```
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "pywebview>=5.0",
```
Run: `uv sync`
Verify: `uv run python -c "import fastapi, uvicorn, webview"` exits 0.
(If `pywebview` fails to build on this machine — it needs a system webview — note
it and continue; Tasks 2–4 and 6 don't import it, only Task 5's `open_window`
and `io run` do. `io serve` and all tests stay green without it.)

- [ ] **Step 2: Write the failing test** — `tests/test_config.py` (append)

```python
def test_service_section_defaults(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://u:p@localhost/db"
        embedding_dim = 768
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    cfg = load_config(p)
    assert cfg.service.host == "127.0.0.1"
    assert cfg.service.port == 8765
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_config.py::test_service_section_defaults -v`
Expected: FAIL — `Config` has no `service`.

- [ ] **Step 4: Implement** — `io_assistant/config.py`

```python
class ServiceConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765
    frontend_dir: str | None = None


class Config(BaseModel):
    database_url: str
    embedding_dim: int
    backend: BackendConfig
    resolver: ResolverConfig
    service: ServiceConfig = ServiceConfig()
```
In `load_config`, before `Config.model_validate(raw)`, ensure a missing section
is fine (it already is — `service` has a default). Nothing else to change.

- [ ] **Step 5: Update `config.toml`** — add:
```toml
[service]
host = "127.0.0.1"
port = 8765
```

- [ ] **Step 6: Update the `config` fixture** — `tests/conftest.py`

```python
from io_assistant.config import Config, BackendConfig, ResolverConfig, ServiceConfig
...
        resolver=ResolverConfig(
            fuzzy_threshold=92, vector_similarity_threshold=0.85,
            confidence_gate_threshold=0.6,
        ),
        service=ServiceConfig(),
```

- [ ] **Step 7: Run**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock config.toml io_assistant/config.py tests/
git commit -m "feat: FastAPI/uvicorn/pywebview deps and [service] config section"
```

---

## Task 2: `create_app()` — `/health` and `POST /utterance`

**Files:**
- Create: `io_assistant/service/__init__.py`, `io_assistant/service/app.py`,
  `io_assistant/service/schemas.py`
- Test: `tests/test_service_health.py`, `tests/test_service_utterance.py`

**Interfaces:**
- Consumes: `Config`, `Orchestrator`, `make_engine`, `make_session_factory`,
  `PendingStore`.
- Produces:
  - `io_assistant.service.schemas`:
    - `UtteranceIn` (pydantic): `text: str`, `source: Literal["text","voice"] = "text"`,
      `confirm_token: str | None = None`.
    - `UtteranceOut` (pydantic): `intent: str`, `message: str`,
      `pending_token: str | None = None`, `stored: bool = False`.
    - `HealthOut` (pydantic): `ok: bool`, `database: bool`, `backend_provider: str`.
  - `io_assistant.service.app.create_app(config: Config, *, orchestrator=None, engine=None) -> FastAPI`
    — builds (or accepts, for tests) one `engine`, `sessionmaker`, and
    `Orchestrator`; stashes them on `app.state`. `app.state.pending:
    dict[str, PendingStore]`.
    - `GET /health` → `HealthOut`: `database` is `True` iff `SELECT 1` succeeds
      on a fresh connection; `backend_provider` from `config.backend.provider`;
      `ok = database`.
    - `POST /utterance` (`UtteranceIn` → `UtteranceOut`):
      - if `confirm_token` is set and present in `app.state.pending`: pop it and
        call `orchestrator.handle(pending.text, pending=pending)`.
      - else: `orchestrator.handle(body.text, source=body.source)`.
      - map `HandleResult` → `UtteranceOut`. If `result.pending` is not None,
        generate a token (`secrets.token_urlsafe(8)`), store
        `result.pending`, and return it as `pending_token`.
      - `stored = result.stored is not None and not getattr(result.stored, "gated", False)`.
  - `create_app` mounts the frontend at `/` in Task 4; for now `GET /`
    returns `{"service": "io", "status": "ok"}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_service_health.py`:
```python
from fastapi.testclient import TestClient
from tests.conftest import requires_db
from io_assistant.service.app import create_app


@requires_db
def test_health_ok(config, fake_backend):
    app = create_app(config, orchestrator=None, engine=None)  # real engine from config
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["database"] is True
    assert body["backend_provider"] == config.backend.provider
```

`tests/test_service_utterance.py`:
```python
import datetime as dt

from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.service.app import create_app
from io_assistant.models_domain import ExtractionResult, ExtractedRecord
from io_assistant.db import models as m


@requires_db
def test_post_utterance_stores(config, fake_backend, db, monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(records=[
        ExtractedRecord(kind="note", title="buy milk", confidence=0.9)]))
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind())
    with TestClient(app) as c:
        r = c.post("/utterance", json={"text": "note: buy milk"})
    assert r.status_code == 200
    body = r.json()
    assert body["intent"] == "store" and body["stored"] is True
    assert db.query(m.Record).filter_by(title="buy milk").count() == 1


@requires_db
def test_post_utterance_gate_then_confirm(config, fake_backend, db, monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(records=[
        ExtractedRecord(kind="note", title="vague thing", confidence=0.2)]))
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind())
    with TestClient(app) as c:
        r1 = c.post("/utterance", json={"text": "maybe something"})
        tok = r1.json()["pending_token"]
        assert tok
        r2 = c.post("/utterance", json={"text": "yes", "confirm_token": tok})
    assert r2.json()["stored"] is True
    assert db.query(m.Record).filter_by(title="vague thing").count() == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_service_health.py tests/test_service_utterance.py -v`
Expected: FAIL — `ModuleNotFoundError: io_assistant.service.app`.

- [ ] **Step 3: Implement `io_assistant/service/schemas.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class UtteranceIn(BaseModel):
    text: str
    source: Literal["text", "voice"] = "text"
    confirm_token: str | None = None


class UtteranceOut(BaseModel):
    intent: str
    message: str
    pending_token: str | None = None
    stored: bool = False


class HealthOut(BaseModel):
    ok: bool
    database: bool
    backend_provider: str
```

- [ ] **Step 4: Implement `io_assistant/service/app.py`**

```python
from __future__ import annotations

import secrets

from fastapi import FastAPI
from sqlalchemy import text

from io_assistant.config import Config
from io_assistant.db.base import make_engine, make_session_factory
from io_assistant.orchestrator import Orchestrator, PendingStore
from io_assistant.service.schemas import HealthOut, UtteranceIn, UtteranceOut


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
            ok=db_ok, database=db_ok,
            backend_provider=config.backend.provider,
        )

    @app.post("/utterance", response_model=UtteranceOut)
    def utterance(body: UtteranceIn):
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
            intent=result.intent, message=result.message,
            pending_token=token, stored=stored,
        )

    return app
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_service_health.py tests/test_service_utterance.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/service/ tests/test_service_health.py tests/test_service_utterance.py
git commit -m "feat: FastAPI service — /health and POST /utterance with gate tokens"
```

---

## Task 3: WebSocket `/ws`

**Files:**
- Modify: `io_assistant/service/app.py`
- Test: `tests/test_service_ws.py`

**Interfaces:**
- Produces:
  - `WS /ws` — the client sends JSON frames `{"text": "...", "source": "text",
    "confirm_token": null}`; the server runs the same logic as `POST /utterance`
    and replies with one frame
    `{"type": "answer", "intent": ..., "message": ..., "pending_token": ...,
    "stored": ...}`. On a malformed frame it replies
    `{"type": "error", "message": "..."}` and keeps the socket open. Token
    streaming of the message is **deferred** (the backend returns a full string);
    the channel exists now so Plan-4 voice output and later unprompted pushes
    reuse it.

- [ ] **Step 1: Write the failing test** — `tests/test_service_ws.py`

```python
from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.service.app import create_app
from io_assistant.models_domain import ExtractionResult, ExtractedRecord
from io_assistant.db import models as m


@requires_db
def test_ws_roundtrip(config, fake_backend, db, monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(records=[
        ExtractedRecord(kind="note", title="ws note", confidence=0.9)]))
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind())
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"text": "note: ws note"})
            reply = ws.receive_json()
    assert reply["type"] == "answer" and reply["stored"] is True
    assert db.query(m.Record).filter_by(title="ws note").count() == 1


@requires_db
def test_ws_bad_frame_keeps_open(config, fake_backend, db):
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind())
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_text("not json")
            reply = ws.receive_json()
    assert reply["type"] == "error"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_service_ws.py -v`
Expected: FAIL — no `/ws` route (connection refused / 403).

- [ ] **Step 3: Implement** — add to `create_app` in `io_assistant/service/app.py`

```python
from fastapi import WebSocket, WebSocketDisconnect
import json as _json
...
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
        stored = result.stored is not None and not getattr(result.stored, "gated", False)
        return UtteranceOut(intent=result.intent, message=result.message,
                            pending_token=token, stored=stored)
```
Refactor the `POST /utterance` body to `return _run(body)`. Then:
```python
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
```
(`orchestrator.handle` is sync and short; running it inline in the async handler
is acceptable for a single-user local service. If it ever blocks noticeably,
wrap in `await anyio.to_thread.run_sync(...)` — noted, not done now.)

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_service_ws.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/service/app.py tests/test_service_ws.py
git commit -m "feat: service WebSocket /ws mirroring POST /utterance"
```

---

## Task 4: Frontend static files + mount

**Files:**
- Create: `frontend/index.html`, `frontend/app.js`, `frontend/styles/app.css`,
  `frontend/vendor/markdown.js`, `frontend/components/message.js`,
  `frontend/views/chat.js`, `frontend/views/timeline.js`,
  `frontend/views/sources.js`, `frontend/views/review.js`
- Modify: `io_assistant/service/app.py` (mount static)
- Test: `tests/test_frontend_assets.py`

**Interfaces:**
- Produces:
  - `create_app` serves `frontend/` (from `config.service.frontend_dir` or the
    repo default `<repo>/frontend`) as static files at `/app` (so `/` stays the
    JSON status probe and `/health` / `/utterance` / `/ws` are unshadowed).
    `GET /app/` returns `index.html`.
  - `frontend/app.js` — a hash router (`#/chat`, `#/timeline`, `#/sources`,
    `#/review`), a `connect()` that opens `ws://<host>/ws`, a tiny state store
    `{transcript: []}`, and `send(text)` that pushes over the WS and appends the
    answer to the transcript. Vanilla ES modules, no build step, no framework.
  - `frontend/vendor/markdown.js` — `export function renderMarkdown(src)`:
    handles `#`/`##`/`###` headings, `-`/`*` bullet lists, ordered lists,
    `**bold**`, `*italic*`, `` `code` ``, fenced ``` blocks, paragraphs, and
    links `[t](url)` — escaping HTML first. A fenced block tagged `mermaid`
    renders as `<pre class="mermaid-src" data-note="diagram">…</pre>` (real
    Mermaid rendering is a later vendor step — tracked in backlog).
  - `frontend/components/message.js` — `renderMessage(role, text, shape)`:
    `shape === "markdown"` → `renderMarkdown`; else text with `\n` → `<br>`,
    HTML-escaped.

- [ ] **Step 1: Write the failing test** — `tests/test_frontend_assets.py`

```python
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_frontend_dir_exists():
    assert (FRONTEND / "index.html").is_file()
    assert (FRONTEND / "app.js").is_file()


def test_no_external_urls_in_frontend():
    offenders = []
    pattern = re.compile(r"https?://(?!(127\.0\.0\.1|localhost))", re.I)
    for path in FRONTEND.rglob("*"):
        if path.suffix.lower() in {".html", ".js", ".css"}:
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, "external URL(s) in frontend:\n" + "\n".join(offenders)


def test_index_served(config):
    from io_assistant.service.app import create_app
    app = create_app(config, orchestrator=object(), engine=object())
    with TestClient(app) as c:
        r = c.get("/app/")
    assert r.status_code == 200 and "<html" in r.text.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_frontend_assets.py -v`
Expected: FAIL — no `frontend/` dir.

- [ ] **Step 3: Create `frontend/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>io</title>
  <link rel="stylesheet" href="./styles/app.css" />
</head>
<body>
  <nav id="nav">
    <span class="brand">io</span>
    <a href="#/chat">Chat</a>
    <a href="#/timeline">Timeline</a>
    <a href="#/sources">Sources</a>
    <a href="#/review">Review</a>
    <span id="conn" class="conn">connecting…</span>
  </nav>
  <main id="view"></main>
  <script type="module" src="./app.js"></script>
</body>
</html>
```

- [ ] **Step 4: Create `frontend/styles/app.css`**

```css
:root { color-scheme: light dark; --fg: #1a1a1a; --bg: #fff; --muted: #666; --accent: #2563eb; }
@media (prefers-color-scheme: dark) { :root { --fg: #e8e8e8; --bg: #16171a; --muted: #999; } }
* { box-sizing: border-box; }
body { margin: 0; font: 15px/1.5 system-ui, sans-serif; color: var(--fg); background: var(--bg); }
#nav { display: flex; gap: 14px; align-items: center; padding: 10px 16px; border-bottom: 1px solid #8883; }
#nav .brand { font-weight: 700; }
#nav a { color: var(--fg); text-decoration: none; opacity: .7; }
#nav a:hover, #nav a.active { opacity: 1; color: var(--accent); }
#nav .conn { margin-left: auto; font-size: 12px; color: var(--muted); }
#view { padding: 16px; max-width: 780px; margin: 0 auto; }
.msg { margin: 10px 0; padding: 10px 12px; border-radius: 10px; white-space: normal; }
.msg.user { background: #2563eb14; }
.msg.io { background: #8881; }
.chat-input { display: flex; gap: 8px; margin-top: 16px; }
.chat-input input { flex: 1; padding: 9px 11px; border-radius: 8px; border: 1px solid #8886; background: var(--bg); color: var(--fg); }
.chat-input button { padding: 9px 16px; border: 0; border-radius: 8px; background: var(--accent); color: #fff; cursor: pointer; }
.stub { color: var(--muted); font-style: italic; }
pre.mermaid-src { background: #8881; padding: 10px; border-radius: 8px; overflow-x: auto; }
pre.mermaid-src::before { content: "diagram (" attr(data-note) ")"; display: block; font-size: 11px; color: var(--muted); margin-bottom: 6px; }
```

- [ ] **Step 5: Create `frontend/vendor/markdown.js`**

```javascript
// Minimal, dependency-free Markdown -> HTML. Local-first: no bundled library.
function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inline(s) {
  return esc(s)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, (m, t, u) =>
      /^https?:\/\/(127\.0\.0\.1|localhost)|^[#./]/.test(u)
        ? `<a href="${esc(u)}">${esc(t)}</a>`
        : esc(t));
}
export function renderMarkdown(src) {
  const lines = String(src).replace(/\r\n/g, "\n").split("\n");
  const out = [];
  let i = 0, list = null;
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  while (i < lines.length) {
    const line = lines[i];
    const fence = line.match(/^```(\w*)/);
    if (fence) {
      closeList();
      const lang = fence[1];
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]);
      i++;
      const body = esc(buf.join("\n"));
      out.push(lang === "mermaid"
        ? `<pre class="mermaid-src" data-note="diagram">${body}</pre>`
        : `<pre><code>${body}</code></pre>`);
      continue;
    }
    const h = line.match(/^(#{1,3})\s+(.*)$/);
    if (h) { closeList(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); i++; continue; }
    const ul = line.match(/^\s*[-*]\s+(.*)$/);
    const ol = line.match(/^\s*\d+\.\s+(.*)$/);
    if (ul || ol) {
      const want = ul ? "ul" : "ol";
      if (list !== want) { closeList(); list = want; out.push(`<${want}>`); }
      out.push(`<li>${inline((ul || ol)[1])}</li>`);
      i++; continue;
    }
    if (!line.trim()) { closeList(); i++; continue; }
    closeList();
    out.push(`<p>${inline(line)}</p>`);
    i++;
  }
  closeList();
  return out.join("\n");
}
```

- [ ] **Step 6: Create `frontend/components/message.js`**

```javascript
import { renderMarkdown } from "../vendor/markdown.js";
function esc(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
export function renderMessage(role, text, shape) {
  const div = document.createElement("div");
  div.className = "msg " + (role === "user" ? "user" : "io");
  div.innerHTML = shape === "markdown"
    ? renderMarkdown(text)
    : esc(String(text)).replace(/\n/g, "<br>");
  return div;
}
```

- [ ] **Step 7: Create `frontend/views/chat.js`**

```javascript
import { renderMessage } from "../components/message.js";

export function mount(root, store, send) {
  root.innerHTML = "";
  const log = document.createElement("div");
  log.id = "log";
  const form = document.createElement("form");
  form.className = "chat-input";
  form.innerHTML = `<input id="q" autocomplete="off" placeholder="Tell io something, or ask a question…" />
    <button type="submit">Send</button>`;
  root.append(log, form);

  const draw = () => {
    log.innerHTML = "";
    for (const m of store.transcript) log.append(renderMessage(m.role, m.text, m.shape));
    log.scrollTop = log.scrollHeight;
  };
  draw();
  store._onChange = draw;

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = form.querySelector("#q");
    const text = q.value.trim();
    if (!text) return;
    q.value = "";
    send(text);
  });
}
```

- [ ] **Step 8: Create the three stub views** — `frontend/views/timeline.js`,
  `sources.js`, `review.js` (identical but for the label):

```javascript
export function mount(root) {
  root.innerHTML = `<p class="stub">Timeline — coming in a later phase.</p>`;
}
```
(`sources.js` → "Sources — connected email / WhatsApp — coming in a later
phase."; `review.js` → "Review — the keep/discard queue — coming in a later
phase.")

- [ ] **Step 9: Create `frontend/app.js`**

```javascript
import { mount as chat } from "./views/chat.js";
import { mount as timeline } from "./views/timeline.js";
import { mount as sources } from "./views/sources.js";
import { mount as review } from "./views/review.js";

const VIEWS = { chat, timeline, sources, review };
const store = { transcript: [], _onChange: null };
const touch = () => store._onChange && store._onChange();

let ws = null;
function connect() {
  const conn = document.getElementById("conn");
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => (conn.textContent = "connected");
  ws.onclose = () => { conn.textContent = "disconnected"; setTimeout(connect, 1500); };
  ws.onerror = () => (conn.textContent = "error");
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "error") {
      store.transcript.push({ role: "io", text: "⚠ " + m.message, shape: "text" });
    } else {
      store.transcript.push({ role: "io", text: m.message, shape: "text" });
      if (m.pending_token) store.pendingToken = m.pending_token;
      else delete store.pendingToken;
    }
    touch();
  };
}
function send(text) {
  store.transcript.push({ role: "user", text, shape: "text" });
  touch();
  const frame = { text, source: "text" };
  if (store.pendingToken && /^(y|yes)$/i.test(text)) frame.confirm_token = store.pendingToken;
  ws.send(JSON.stringify(frame));
}

function route() {
  const name = (location.hash.replace(/^#\//, "") || "chat");
  const view = VIEWS[name] || chat;
  for (const a of document.querySelectorAll("#nav a"))
    a.classList.toggle("active", a.getAttribute("href") === `#/${name}`);
  view(document.getElementById("view"), store, send);
}

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", () => { connect(); route(); });
```

- [ ] **Step 10: Mount static in `create_app`** — `io_assistant/service/app.py`

```python
from pathlib import Path
from fastapi.staticfiles import StaticFiles
...
    frontend = Path(config.service.frontend_dir) if config.service.frontend_dir \
        else Path(__file__).resolve().parents[2] / "frontend"
    if frontend.is_dir():
        app.mount("/app", StaticFiles(directory=str(frontend), html=True), name="frontend")
```
(Place after the routes are defined; `object()` orchestrator/engine in the asset
test never gets called because the test only hits `/app/`.)

- [ ] **Step 11: Run**

Run: `uv run pytest tests/test_frontend_assets.py -v`
Expected: PASS.

- [ ] **Step 12: Commit**

```bash
git add frontend/ io_assistant/service/app.py tests/test_frontend_assets.py
git commit -m "feat: vendored static frontend (chat active, stubs) served at /app"
```

---

## Task 5: `io serve` + `io run` (pywebview)

**Files:**
- Create: `io_assistant/service/runner.py`
- Modify: `io_assistant/cli.py`
- Test: `tests/test_cli_serve.py`

**Interfaces:**
- Produces:
  - `io_assistant.service.runner.run_service(config, *, block=True)` — starts
    `uvicorn` on `config.service.host:port` serving `create_app(config)`. With
    `block=False` returns a `(server, thread)` handle for `io run` to manage.
  - `io_assistant.service.runner.open_window(url: str, title: str = "io")` —
    imports `webview` lazily, creates a window, and `webview.start()`s. Raises
    `RuntimeError` with a clear message if `pywebview` is not importable.
  - `io serve` (Typer) — `run_service(load_config(), block=True)`; Ctrl-C exits.
  - `io run` (Typer) — start the service on a background thread, wait for
    `/health` to return `ok`, then `open_window(f"http://{host}:{port}/app/")`;
    when the window closes, stop the server and exit.

- [ ] **Step 1: Write the failing test** — `tests/test_cli_serve.py`

```python
from typer.testing import CliRunner
from io_assistant.cli import app


def test_serve_command_registered():
    result = CliRunner().invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "service" in result.output.lower()


def test_run_command_registered():
    result = CliRunner().invoke(app, ["run", "--help"])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_cli_serve.py -v`
Expected: FAIL — no `serve` / `run` commands.

- [ ] **Step 3: Implement `io_assistant/service/runner.py`**

```python
from __future__ import annotations

import threading
import time

import httpx
import uvicorn

from io_assistant.config import Config
from io_assistant.service.app import create_app


def run_service(config: Config, *, block: bool = True):
    server = uvicorn.Server(uvicorn.Config(
        create_app(config),
        host=config.service.host,
        port=config.service.port,
        log_level="warning",
    ))
    if block:
        server.run()
        return None
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://{config.service.host}:{config.service.port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/health", timeout=0.5).json().get("ok"):
                break
        except Exception:
            pass
        time.sleep(0.1)
    return server, thread


def open_window(url: str, title: str = "io") -> None:
    try:
        import webview
    except Exception as e:  # pragma: no cover - platform dependent
        raise RuntimeError(
            "pywebview is not available. Run `io serve` and open "
            f"{url} in a browser instead."
        ) from e
    webview.create_window(title, url, width=980, height=720)
    webview.start()
```

- [ ] **Step 4: Add CLI commands** — `io_assistant/cli.py`

```python
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
```

- [ ] **Step 5: Run**

Run: `uv run pytest tests/test_cli_serve.py -v`
Expected: PASS.

- [ ] **Step 6: Manual smoke** (record the result in the commit message)

```bash
uv run io serve
# in another shell:
curl -s localhost:8765/health
curl -s -XPOST localhost:8765/utterance -H 'content-type: application/json' -d '{"text":"note: test"}'
```
Then `uv run io run` and confirm the window opens to the chat view (or, if
`pywebview` has no system webview here, that it prints the browser-fallback
message and `io serve` + `http://localhost:8765/app/` works in a browser).

- [ ] **Step 7: Commit**

```bash
git add io_assistant/service/runner.py io_assistant/cli.py tests/test_cli_serve.py
git commit -m "feat: io serve (headless) and io run (pywebview window)"
```

---

## Task 6: HTTP end-to-end + docs

**Files:**
- Create: `tests/test_service_e2e.py`, `.claude/knowledge/desktop-app.md`
- Modify: `.claude/knowledge/conventions.md`, `.claude/state/*`

**Interfaces:**
- Consumes: the whole service.
- Produces: two `@requires_db` tests driving spec §9 scenarios 1 and 2 through
  `POST /utterance` (store, then query), and a knowledge doc.

- [ ] **Step 1: Write the tests** — `tests/test_service_e2e.py`

```python
import datetime as dt

from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.service.app import create_app
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedRecord)
from io_assistant.db import models as m


@requires_db
def test_store_then_query_over_http(config, fake_backend, db, monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind())

    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        records=[ExtractedRecord(kind="event", domain="social",
                                 title="dinner with Nafay", when_phrase="today",
                                 people=["Nafay"], places=["Arcadian"],
                                 confidence=0.9)]))
    with TestClient(app) as c:
        r1 = c.post("/utterance", json={"text": "dinner with Nafay at Arcadian"})
        assert r1.json()["stored"] is True

        fake_backend.set_intent("query")
        fake_backend.set_plan({"subqueries": [{"target_type": "record",
                              "kind_filter": ["event"], "entities": ["Nafay"]}],
                              "answer_shape": "text"})
        fake_backend.set_answer("You had dinner with Nafay at Arcadian.")
        r2 = c.post("/utterance", json={"text": "when did I see Nafay?"})
    assert r2.json()["intent"] == "query"
    assert "Nafay" in r2.json()["message"]
    assert db.query(m.Record).filter_by(title="dinner with Nafay").count() == 1
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_service_e2e.py -v`
Expected: PASS.

- [ ] **Step 3: Write `.claude/knowledge/desktop-app.md`**

Cover: the service is `io_assistant/service/` — `create_app(config)` builds one
engine + Orchestrator; `/health`, `POST /utterance` (with `confirm_token` gate
flow), `WS /ws`. The gate is carried in `app.state.pending` (in-memory,
single-user). Frontend is vendored static files at `/app` — hash router, WS
client, hand-rolled `vendor/markdown.js` (no CDN — that is the local-first
line). `io serve` = headless, `io run` = service + `pywebview`. Token streaming
and real Mermaid rendering are deferred.

- [ ] **Step 4: Update `.claude/knowledge/conventions.md`** — add: "The service
  binds `127.0.0.1` only; the frontend references no external URLs
  (`tests/test_frontend_assets.py` enforces). `io run` opens the window;
  `io serve` is headless."

- [ ] **Step 5: Full suite**

Run: `uv run pytest -q`
Expected: PASS. Confirm the local-first socket guard in
`tests/test_e2e_store.py` still passes.

- [ ] **Step 6: Update state + commit**

Move Plan 3 from `backlog.md` to `completed.md` (dated). Then:
```bash
git add tests/test_service_e2e.py .claude/
git commit -m "test: HTTP store-then-query e2e; desktop-app knowledge doc"
```

---

## Self-Review

**Spec coverage (§7):**
- "Orchestrator runs as a local FastAPI service" → Task 2 (`create_app`).
- "REST endpoints (`POST /utterance`, `GET /health`)" → Task 2.
- "WebSocket channel for streaming / unprompted pushes" → Task 3 (channel
  exists; token streaming explicitly deferred).
- "CLI (`io run`) and desktop app both clients of one service" → Task 5;
  `io serve` for headless (voice client in Plan 4).
- "structured HTML/JS app (not a single file) in a pywebview window" → Task 4
  (`frontend/` with `app.js` router, `views/`, `components/`) + Task 5
  (`open_window`).
- "one `renderMessage()` handles all output; Markdown renders; ```mermaid
  renders as diagrams" → Task 4 `components/message.js` + `vendor/markdown.js`
  (mermaid fence rendered as a labelled block; real diagram rendering deferred,
  backlog).
- "all JS/CSS vendored, no CDN" → Task 4 + `tests/test_frontend_assets.py`.
- "chat fully functional; timeline/sources/review routed with placeholder" →
  Task 4 (`views/`).

**Local-first check:** service binds `127.0.0.1`; frontend asset lint test
(`test_frontend_assets.py`) fails on any non-local `http(s)://`; the markdown
link renderer drops non-local link hrefs to plain text.

**Deferred (recorded in `backlog.md` at execution):** token-by-token streaming
over `/ws`; real Mermaid rendering (needs a vendored lib — a deliberate,
reviewed download); running `orchestrator.handle` off the event loop thread;
`GET /utterances` history endpoint.

**Placeholder scan:** none — every file's full content is in the plan; every
step has a runnable command.

**Type consistency:**
- `UtteranceIn` / `UtteranceOut` / `HealthOut` fields identical across Tasks 2,
  3, 6.
- `create_app(config, *, orchestrator=None, engine=None)` signature identical in
  Tasks 2, 3, 4, 5, 6.
- `run_service(config, *, block=True)` return contract (`None` when blocking,
  `(server, thread)` otherwise) consistent between `runner.py` and `io run`.
- `frontend/` module paths (`./views/chat.js`, `../components/message.js`,
  `../vendor/markdown.js`) match the file structure.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between.
   Order: 1 → 2 → 3 → 4 → 5 → 6 (linear; 3 depends on 2, 4 on 2, 5 on 2+4).
2. **Inline Execution** — `superpowers:executing-plans`, batched with checkpoints.
