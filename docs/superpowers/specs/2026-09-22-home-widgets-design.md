# Home-screen widgets + pending-tasks window

Date: 2026-09-22 · Status: approved

## Goal

A home screen the user can arrange: premade widgets (to-do, weather, time zones,
important emails/notifications) on a snap grid, plus a small always-on-top window
that shows pending tasks. Cost: $0.

## Decisions (from brainstorming)

- **Weather:** Open-Meteo (free, no key). **Email:** Gmail read-only through the
  user's Google account (a separate sign-in from sync). **Layout:** 4-column
  snap grid, sizes S/M/L. **Tasks window:** compact, frameless, always-on-top,
  bottom-right, *not draggable* (the standing "IO windows are never draggable"
  rule), single instance.

## Design

1. **Widgets** (`type`): `todo`, `weather`, `timezones`, `alerts`. All four are in
   the default layout on first run. Sizes: S = 1×1, M = 2×1, L = 2×2 cells.
   - `todo`: open/overdue tasks and chores (overdue → today → upcoming → undated),
     tick to complete via the existing `PATCH /record/{id}`; a header button opens
     the tasks window.
   - `weather`: current temperature, feels-like, condition, hi/lo and a 3-day
     outlook for one chosen city.
   - `timezones`: a list of IANA zones shown as local time, weekday and UTC offset;
     computed in the browser with `Intl` (no network); editable.
   - `alerts` ("Important"): IO's own alerts (overdue tasks, today's tasks,
     occasions within 7 days) plus unread important/starred Gmail (sender + subject).
2. **Board** (`frontend/widgets/`): pure layout math (`layout.js`: place, move with
   push-down, resize, remove, compact, normalize) drives a grid; edit mode (an
   icon in the ask bar) shows drag handles, S/M/L buttons, remove, and an
   add-widget picker. It sits under the clock, above the ask bar.
3. **Persistence:** `GET/PUT /widgets` ⇄ `~/.local/share/io/widgets.json`
   (`{v, layout[], settings{}}`), validated. Not `localStorage` (pywebview runs in
   private mode) and not synced (layout is per-device).
4. **Backend** (`io_assistant/widgets/`): `tasks.py` (`pending_tasks`, `alerts`),
   `weather.py` (`search_city`, `forecast`, 10-minute cache, WMO code → label),
   `gmail.py` (`GmailConnector`: connect/disconnect/status/`important`).
   Endpoints: `GET /tasks`, `GET /alerts`, `GET /weather/search?q=`,
   `GET /weather?lat=&lon=`, `GET /gmail`, `POST /gmail/connect`,
   `POST /gmail/disconnect`, `GET /gmail/important`.
5. **Network + rules:** the *service* makes every outbound call, never the browser.
   Case 9 `geocoding-api.open-meteo.com` + `api.open-meteo.com`: only when a weather
   widget has a city; only the city name / coordinates are sent. Case 10
   `gmail.googleapis.com` + sign-in hosts: only after "Connect Gmail"; scope
   `gmail.readonly`; message *metadata* only (From, Subject, Date), never bodies;
   its own keychain token so sync's Drive-only consent is not widened. Gmail
   access is a restricted scope: the user's own project shows an unverified-app
   warning to click through. The OAuth client is the one in `[sync]`.
6. **Tasks window:** `js_api.open_tasks()` creates (or focuses) a 340×520
   frameless, `on_top` window at the screen's bottom-right, URL `<app>/#tasks`.
   That route renders only the task list (same component as the widget), polling
   `/tasks` every 15 s, with its own close button.

## Testing

Layout math and time-zone formatting: node tests, written first. Task/alert
endpoints and the widgets file: real Postgres and a temp path. Weather and Gmail:
parsed from canned responses and a fake Gmail service (no live calls in the
suite; one live Open-Meteo call by hand). UI states: browser pane with stubbed
API. **Not verifiable here:** the native pywebview window's always-on-top and
position.

## Out of scope

Syncing the layout across devices; free-form placement; email bodies/replying;
widgets for other providers; user-authored widgets.
