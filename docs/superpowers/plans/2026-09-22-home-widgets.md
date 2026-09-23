# Home Widgets + Tasks Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Arrangeable premade home-screen widgets (to-do, weather, time zones, important) and a small always-on-top pending-tasks window.

**Architecture:** Pure layout math in JS drives a snap-grid board on the standby view. Data comes from small service endpoints (`/tasks`, `/alerts`, `/weather*`, `/gmail*`); the layout persists to a local JSON file via `/widgets`. The tasks window is a second pywebview window rendering the same task component at route `#tasks`.

**Tech Stack:** Python/FastAPI/SQLAlchemy, httpx, google-api-python-client (Gmail), vanilla ES modules, node for pure-JS tests, pytest.

**Spec:** `docs/superpowers/specs/2026-09-22-home-widgets-design.md`

## Global Constraints

- Local-first: only the service calls out (Open-Meteo; Gmail after connect); never the browser (CSP/asset test forbids non-local URLs in frontend). New rules: cases 9 and 10.
- UI: no borders/outlines on controls; every colour through tokens; both themes; every flex view needs `min-height: 0`; the tasks window is not draggable.
- Real Postgres in tests; no live network in the suite.
- Commit per task. Test command: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run pytest -q -p no:warnings`.

## Tasks

### 1. Layout math + widgets file
Files: `frontend/widgets/layout.js`, `io_assistant/widgets/store.py`, `service/app.py` (`GET/PUT /widgets`); tests `tests/test_frontend_layout.py`, `tests/test_widgets_store.py`.
- `layout.js`: `COLS=4`, `SIZES`, `span`, `place`, `move`, `resize`, `remove`, `normalize`. Tests first (node): first free slot; wraps to next row; move pushes a collision down; resize S→L pushes neighbours; col clamped to fit; remove compacts up; normalize repairs bad input; deterministic.
- `store.py`: `load(path) -> dict | None`, `save(path, doc)`, `validate(doc)` (types ∈ todo/weather/timezones/alerts, sizes S/M/L, ≤ 24 widgets, settings ≤ 20 KB). Endpoint returns `{"layout": null}` when the file is missing.

### 2. Tasks + alerts endpoints
Files: `io_assistant/widgets/tasks.py`, `service/app.py`; test `tests/test_widgets_tasks.py` (real DB).
- `pending_tasks(session, now, limit=50)`: open `task`/`chore`, ordered overdue → today → upcoming → undated, each with `id,title,kind,due_at,overdue,due_label`.
- `alerts(session, now)`: overdue count + titles, today's tasks, occasions within 7 days.

### 3. Weather
Files: `io_assistant/widgets/weather.py`, `service/app.py`; test `tests/test_widgets_weather.py` (canned JSON, injected fetcher).
- `search_city(q, fetch)`, `forecast(lat, lon, fetch, now)` with a 10-minute cache; `weather_label(code)`; endpoints return 502 with a readable `detail` on upstream failure; empty query → `[]`.

### 4. Gmail connector
Files: `io_assistant/sync/auth.py` (parametrise scopes/keychain account), `io_assistant/widgets/gmail.py`, `service/app.py`; test `tests/test_widgets_gmail.py` (fake auth + fake Gmail service).
- `GmailConnector.status/connect/disconnect/important`; query `is:unread (is:important OR is:starred)`; metadata only; sender display name parsed from `From`.

### 5. Frontend board + widgets
Files: `frontend/widgets/{board,todo,weather,timezones,alerts,tz}.js`, `frontend/views/standby.js`, `frontend/api.js`, `frontend/app.css`; test `tests/test_frontend_tz.py`.
- Verify in the browser pane (dark + light): default layout, edit mode drag/resize/remove/add, each widget's states (empty, error, data).

### 6. Tasks window
Files: `service/runner.py` (`open_tasks`, single instance, bottom-right, on_top), `frontend/views/tasks.js`, `frontend/app.js` (`#tasks` route), `frontend/app.css`; docs and state.
- Verify the `#tasks` route in the browser pane; native window behaviour is not verifiable here.

## Self-review
Spec coverage: widgets (T5), board + persistence (T1, T5), backend + endpoints (T2-T4), rules (T3, T4 docs), tasks window (T6). Names: `pending_tasks`, `alerts`, `search_city`, `forecast`, `GmailConnector`, `layout.js` API.
