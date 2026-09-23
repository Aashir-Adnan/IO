# Design: migrate the desktop shell from pywebview to Tauri

**Status:** proposed (2026-09-09). Not scheduled. Needs review before a plan.

## Why

The current shell is `pywebview` 6.2 over WebView2 (`io_assistant/service/
runner.py`). It works, but it fights us on the things a "proper GUI" needs:

- **Window chrome.** Frameless + transparent + acrylic is a pile of
  `DwmSetWindowAttribute` ctypes calls that half-work; WebView2 paints opaque
  behind the page so the acrylic never really shows. Drag / no-drag,
  fullscreen state, and geometry persistence are all hand-rolled and flaky
  (this is what the "why can I still drag the window" reports keep hitting).
- **One process, one language.** The GUI lives inside the Python service
  process. A crash in either takes both down. PyInstaller bundles a 350 MB
  one-dir because the whole Python runtime ships.
- **No real IPC.** `js_api` is a thin bridge; anything richer (native menus
  that reflect app state, tray, notifications, deep links, multi-window) is a
  slog.

Tauri keeps our entire web frontend (it's a webview either way) and replaces
the shell with a small Rust host that has first-class APIs for all of the
above, a ~10 MB installer, and process isolation.

## What stays exactly the same

- The **web frontend** (`frontend/`) — vanilla ES modules, no build step. It's
  served over HTTP today; under Tauri it's either served the same way or
  loaded from the bundle. Zero component changes.
- The **Python service** (`io_assistant/service/`) — still a local FastAPI on
  `127.0.0.1:8765`. Tauri launches it as a **sidecar** process and shuts it
  down on exit. All the `/…` and `/ws…` endpoints are untouched.
- **Local-first.** Tauri's updater / telemetry / any phone-home is disabled in
  `tauri.conf.json`. The CSP is locked to `self` + `127.0.0.1` + the two
  sanctioned hosts from `rules/local-first.md`.

## What changes

| Concern | pywebview today | Tauri |
|---|---|---|
| Shell language | Python (`runner.py`) | Rust (`src-tauri/`) |
| Window | frameless + ctypes DWM hacks | `decorations: false`, `transparent: true`, native effects API (`window-vibrancy` crate → real Mica/acrylic) |
| Drag | CSS `app-region` + `easy_drag` | `data-tauri-drag-region` on explicit elements only; **nothing else drags** |
| Fullscreen / geometry | manual JSON file | `tauri-plugin-window-state` |
| Service lifecycle | in-process thread | `tauri.conf.json` `bundle.externalBin` sidecar; killed on `RunEvent::Exit` |
| Bundle | PyInstaller one-dir (~350 MB) | `.msi` / `.exe`, Python sidecar still PyInstaller'd but the shell adds ~6 MB |
| Native menu / tray / notifications | pywebview menu only | `tauri::menu`, `tauri-plugin-notification`, tray |
| Frozen entry | `io_assistant/app_entry.py` | `src-tauri` `main.rs`; `app_entry` becomes the sidecar entry (`io serve` headless) |

## Architecture

```
┌─ Tauri app (Rust) ──────────────────────────────┐
│  main.rs                                         │
│   • spawn sidecar: io-service (PyInstaller exe)  │
│   • wait for GET /health 200                     │
│   • create_window → load http://127.0.0.1:8765/app/ │
│   • window-vibrancy: apply_mica(&window)         │
│   • menu, tray, window-state plugin              │
│   • on exit: SIGTERM the sidecar                 │
└─────────────────────────────────────────────────┘
        │ HTTP + WS on 127.0.0.1:8765 (unchanged)
┌─ io-service (Python, PyInstaller) ──────────────┐
│  cli.serve() → uvicorn → create_app()           │
│  (identical to today's `io serve`)              │
└─────────────────────────────────────────────────┘
```

The frontend keeps talking to `location.host` — under Tauri the window's URL
*is* `127.0.0.1:8765`, so `api.js` and the WebSocket code need **no change**.
(Alternative: load the frontend from the Tauri bundle via `tauri://localhost`
and point `api.js` at an absolute `http://127.0.0.1:8765`. Decide during the
plan — serving from the service is simpler and matches dev.)

`window.pywebview.api.*` calls in `app.js` (`minimize`, `close`,
`toggle_fullscreen`, `is_fullscreen`, `pick_folder`, `effects`) get a thin
shim: `frontend/shell.js` exposes the same names, backed by
`@tauri-apps/api` (`getCurrentWindow().minimize()` etc.) when
`window.__TAURI__` is present, and no-ops in a plain browser. ~40 lines.

## New tree

```
src-tauri/
  Cargo.toml
  tauri.conf.json          # window, CSP, bundle, sidecar, no updater
  build.rs
  src/main.rs              # spawn sidecar, health-gate, window, menu, vibrancy
  icons/                   # from assets/io.ico
packaging/
  build_tauri.ps1          # PyInstaller the sidecar → src-tauri/bin/ → tauri build
frontend/
  shell.js                 # NEW — pywebview.api ⇆ @tauri-apps/api shim
```

`runner.py` is retired (kept for `io run` dev fallback, or deleted — decide).
`packaging/io.spec` splits: `io-service.spec` (the sidecar, no GUI) stays;
the GUI is Tauri.

## Migration phases

1. **Sidecar-ready service.** Make `io serve` the canonical headless entry;
   confirm `ensure_database` + `/health` gate work when launched as a child
   process with a clean env. (Mostly already true.)
2. **Rust shell, dev only.** `src-tauri` that spawns `uv run io serve`, health-
   gates, opens the window at `/app/`. `frontend/shell.js` shim. Dev parity
   with `dev.ps1 up -Window`.
3. **Native polish.** `window-vibrancy` Mica, `tauri-plugin-window-state`,
   native menu mirroring today's (New chat / Reload / Fullscreen), drag only
   on `data-tauri-drag-region` (which we'll put on *nothing* — the window is
   non-draggable by request).
4. **Bundle.** `build_tauri.ps1`: PyInstaller the sidecar → `src-tauri/bin/
   io-service-x86_64-pc-windows-msvc.exe` → `tauri build` → `.msi`. Verify
   clean-machine launch (Docker Desktop still the one prereq).
5. **Cut over.** `dev.ps1` `up -Window` / `build` / `install` call Tauri.
   Delete `runner.py` + GUI bits of `io.spec`. Update `.claude/knowledge/
   desktop-app.md`.

Each phase is independently shippable; the web UI and service keep working
throughout.

## Costs / risks

- **Rust toolchain** is a new build dependency (`rustup` + MSVC build tools).
  CI needs it. Acceptable — it's the price of a real shell.
- **Two PyInstaller targets** briefly (service + old GUI) during phases 2–4.
- **WebView2 is still the renderer** — so any WebView2-specific rendering
  quirk we have today stays. Tauri fixes the *shell*, not the engine.
- `@tauri-apps/api` is an npm package. To honour "no build step / no CDN" we
  vendor the ESM build into `frontend/vendor/tauri/` like the other vendored
  libs, or use the `withGlobalTauri` option (exposes `window.__TAURI__`
  without imports) — **prefer `withGlobalTauri`**, zero vendoring.

## Open questions for review

1. Serve the frontend from the service (simplest) or from the Tauri bundle
   (offline-loadable, needs absolute API base)?
2. Keep `runner.py` as a `pip install`-only fallback for people who don't want
   the Tauri binary, or delete it?
3. Tray + "minimise to tray" — in scope for the first cut or later?
4. macOS/Linux — Tauri makes these near-free; do we want them now or stay
   Windows-only?
