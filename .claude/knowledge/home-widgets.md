# Home-screen widgets + tasks window

Spec `docs/superpowers/specs/2026-09-22-home-widgets-design.md`, plan
`docs/superpowers/plans/2026-09-22-home-widgets.md`.

## Frontend — `frontend/widgets/`
- `layout.js` — pure snap-grid math (`COLS=4`; S 1×1, M 2×1, L 2×2): `place`, `move`
  (pushes collisions down), `resize`, `remove`, `normalize`. Node-tested
  (`tests/test_frontend_layout.py`). Never mutates its input.
- `board.js` — `mountBoard(host, ctx)` renders the grid on the standby view; edit mode
  (ask-bar `squaresFour` button) = drag cards between cells (HTML5 DnD), S/M/L, remove,
  add, reset. Saves debounced through `PUT /widgets`. Widget settings are keyed by
  widget id (`settings[id]`), so several weather/clock widgets can coexist.
- `index.js` — `WIDGETS` registry (`todo`, `weather`, `timezones`, `alerts`) and the
  premade `defaultLayout()`. A widget's `mount(el, ctx, {size, id, settings:{get,set}})`
  returns a cleanup fn. **To add a widget:** module + registry entry + the type in
  `io_assistant/widgets/store.py` `WidgetItem.type`.
- `todo.js` (also the whole tasks window), `weather.js`, `timezones.js` (+ `tz.js`,
  Intl only, node-tested), `alerts.js` (IO alerts + Gmail).
- `views/tasks.js` — route `#tasks` (`app.js` sets `<html data-mode="tasks">`, hides the
  topbar, skips the rest of boot).

## Backend — `io_assistant/widgets/`
- `store.py` — layout file `~/.local/share/io/widgets.json` (`WidgetsDoc` validation:
  types, sizes, ≤24 widgets, settings ≤20 KB). Per-device, NOT synced, and not
  `localStorage` (pywebview runs private mode). `GET/PUT /widgets`.
- `tasks.py` — `pending_tasks` (open task/chore: overdue → today → upcoming → undated;
  "overdue" is by UTC *date*, so a bare task due 00:00 today is "today") and `alerts`.
  `GET /tasks`, `GET /alerts`. Completion is `PATCH /record/{id}` `{status:"done"}`.
- `weather.py` — Open-Meteo geocoding + forecast, 10-min cache, WMO labels.
  `GET /weather/search?q=`, `GET /weather?lat=&lon=` (502 on upstream failure).
- `gmail.py` — `GmailConnector`: `gmail.readonly`, **metadata only**, its own keychain
  entry (`google-gmail-refresh-token`), same OAuth client as `[sync]`. Query
  `is:unread (is:important OR is:starred)`. `GET /gmail`, `POST /gmail/connect|disconnect`,
  `GET /gmail/important`. Needs the **Gmail API enabled** in the same Google Cloud
  project and the `gmail.readonly` scope added to the consent screen
  (`memory-sync.md` has the project setup).
- Rules: `local-first.md` cases 9 (Open-Meteo) and 10 (Gmail).

## Tasks window
`runner.open_tasks_window(app_url)`: 340×520, frameless, `on_top`, bottom-right,
`easy_drag=False` (IO windows never drag), single instance (second call restores it).
Opened from the To-do card's header button via `window.pywebview.api.open_tasks()`;
`TasksApi.close()` closes it. **The native window's always-on-top/position was not
verified live** (only the `#tasks` view in a browser and the logic against a fake
`webview` module).
