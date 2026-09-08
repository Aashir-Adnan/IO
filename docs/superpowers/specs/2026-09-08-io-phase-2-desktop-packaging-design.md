# IO Phase 2 · Spec B — Desktop Packaging (exe, icon, single-instance)

> Independent of Specs A and C — can be built any time. Turns `io run` into a
> double-clickable Windows application with IO's logo, that refuses to start a
> second copy.

## 1. Vision & scope

Today launching IO means `dev.ps1 up -Window` or a shortcut to a PowerShell
script. This spec produces:

1. **`IO.exe`** — a PyInstaller bundle of `io run` (service + pywebview window),
   with IO's logo as the executable and window icon.
2. **Single-instance** — a second launch does not spin up a second service or
   window; it surfaces the running one and exits.
3. `dev.ps1 build` to produce it and `dev.ps1 install` to drop a Desktop
   shortcut to the built exe (replacing the current script shortcut).

### In scope

- `assets/io-logo.png` (user-supplied source) → `assets/io.ico` (multi-size,
  generated).
- `io_assistant/app_entry.py` — the frozen entry point.
- `io_assistant/service/singleton.py` — cross-process single-instance lock +
  "surface the running instance" behaviour.
- `packaging/io.spec` — the PyInstaller spec.
- `dev.ps1`: `build`, updated `install`.
- Docs + `.claude/state`.

### Out of scope (backlog)

- macOS `.app` / Linux packaging, auto-update, code signing, an installer
  (`.msi`). v1 ships an unsigned `dist/IO/` folder + shortcut.
- Native OS-level window focus of another process's pywebview window (platform
  APIs differ) — v1 opens the app URL in the default browser as the "surface"
  fallback and notes native focus as a follow-up.

## 2. Global constraints

- **local-first** — the bundle contains no network calls beyond the sanctioned
  backend. No telemetry from PyInstaller's bootloader (default). The socket
  guard test is unaffected (packaging adds no imports to the tested paths).
- Models (Whisper / Piper) are **not** bundled — they download at first use to
  `~/.local/share/io/` exactly as today.
- `config.toml` is bundled as a **default**; a user copy in the working
  directory / `~/.config/io/` still wins (existing `load_config` behaviour;
  extend it to also check `~/.config/io/config.toml` if not already).
- Package stays `io_assistant`; the exe is named `IO`.

## 3. Logo & icon

- **Input:** `assets/io-logo.png` — the user drops their logo here (the blurple
  "IO" mark on the dark ground). Required before `dev.ps1 build`.
- `scripts/make_icon.py` — `Pillow`: open the PNG, ensure square (pad
  transparent to square if needed), emit `assets/io.ico` containing
  16/32/48/64/128/256 px. Also emit `assets/io-512.png` (padded) for the
  pywebview window and the frontend favicon.
- `frontend/` favicon: reference `assets/io-512.png` via a route or copy it to
  `frontend/vendor/io-512.png` at build time; the window title stays "IO".

## 4. Single-instance — `io_assistant/service/singleton.py`

```python
def acquire_single_instance(name: str = "io-assistant") -> SingleInstance | None:
    """Return a handle if we are the first instance, else None."""
```

- **Windows:** `ctypes.windll.kernel32.CreateMutexW(None, False,
  f"Global\\{name}")`; if `GetLastError() == ERROR_ALREADY_EXISTS (183)` →
  return `None` (keep the handle open otherwise; releasing it on exit is
  automatic on process death, explicit `close()` in a `finally`).
- **POSIX:** `fcntl.flock` on `~/.local/share/io/<name>.lock`, non-blocking;
  `BlockingIOError` → `None`.
- `SingleInstance` is a context manager; `release()` closes the handle / unlocks.

The guard lives in **`cli.run()`** (single source of truth); `app_entry.py` is
a thin frozen entry point that just calls `cli.run()`.

```python
# io_assistant/cli.py :: run()
inst = acquire_single_instance()
if inst is None:
    surface_running_instance(load_config())   # GET /health; if up, open /app/ in browser; print a line
    raise SystemExit(0)
with inst:
    ...  # existing run() body: start service if needed, open the window
```

`surface_running_instance(config)` — `httpx.get(base + "/health")`; if ok, open
`webbrowser.open(base + "/app/")` and print
*"IO is already running — opened it in your browser."*; if not reachable within
~2 s, print *"IO seems to be starting already."* and exit anyway (never start a
competing service).

## 5. PyInstaller — `packaging/io.spec`

- **mode:** `--onedir` (faster cold start than `--onefile`; ships `dist/IO/`).
- **windowed** (no console).
- **icon:** `assets/io.ico`.
- **name:** `IO`.
- **entry:** `io_assistant/app_entry.py`.
- **datas:** `frontend/`, `config.toml`, `io_assistant/db/migrations/`,
  `io_assistant/prompts/`, `assets/io-512.png`.
- **hiddenimports:** anything PyInstaller misses — `uvicorn` workers,
  `pgvector`, `psycopg` (+ `psycopg_binary`), `webview` platform backend
  (`webview.platforms.winforms` / `edgechromium`), `pypdf`, `docx`, `pydantic`
  internals. Enumerate during the build task and pin in the spec.
- Alembic: `alembic upgrade head` at startup needs the `versions/` dir on disk
  and `alembic.ini` — bundle both; `app_entry` sets the script location to the
  bundled path (`sys._MEIPASS`).
- **Postgres is not bundled.** The frozen app still expects Docker Postgres (or
  a user-configured `database_url`). `app_entry` shows a clear dialog (pywebview
  `create_confirmation_dialog` / a simple error window) if the DB is
  unreachable, pointing at `dev.ps1 up` or Docker — it does not try to start
  Docker itself.

## 6. `dev.ps1` changes

- `dev.ps1 build`:
  1. assert `assets/io-logo.png` exists (fail with instructions otherwise).
  2. `uv run python scripts/make_icon.py`.
  3. `uv run pyinstaller packaging/io.spec --noconfirm`.
  4. print the path to `dist/IO/IO.exe`.
- `dev.ps1 install` — now: ensure `dist/IO/IO.exe` exists (run `build` if not),
  create `Desktop\IO.lnk` → `dist/IO/IO.exe`, `WorkingDirectory =
  <repo root>`, `IconLocation = assets\io.ico`. (Drop the PowerShell-script
  shortcut.)
- `dev.ps1 up -Window` stays as the dev path (no packaging needed).
- New dev-group dep: **`pyinstaller`**.

## 7. Testing

Packaging can't run a full PyInstaller build in the normal suite (minutes,
platform-specific), so:

| file | covers |
|---|---|
| `tests/test_singleton.py` | POSIX `flock` path: first `acquire` returns a handle, second returns `None`, `release` frees it; the lock file lands under the expected dir. Windows mutex path is `skipif not win32` with a minimal same-shape assertion. |
| `tests/test_make_icon.py` | `make_icon` on a fixture PNG produces `io.ico` that `PIL` can open with ≥ 4 embedded sizes; non-square input is padded. |
| `tests/test_packaging_spec.py` | parse `packaging/io.spec` (it's Python); assert every `datas` source path exists in the repo; assert the entry module exists. No build. |
| `tests/test_cli_serve.py` (extend) | `cli.run` calls `acquire_single_instance`; when it returns `None`, `run` exits 0 without starting a server (monkeypatch). |

`dev.ps1 build` is a **manual** verification step, documented in
`.claude/skills/run-local.md` and the plan's final task ("run `dev.ps1 build`
on Windows, double-click `dist/IO/IO.exe`, confirm the window opens fullscreen
with the icon, launch it again, confirm the second launch surfaces the first
and exits").

## 8. Risks & decisions

- **`--onedir` vs `--onefile`** — onedir chosen for start-up speed and simpler
  Alembic/data bundling; the Desktop shortcut hides the folder.
- **DB dependency** — the frozen app does not manage Postgres; it fails loudly
  with guidance. Bundling an embedded Postgres is out of scope.
- **Hidden imports** are the usual PyInstaller pain; the build task enumerates
  them against a clean `dist/` run and pins them in `io.spec`.
- **Unsigned exe** — SmartScreen will warn on first run; acceptable for a
  single-user local tool. Signing is backlog.
- **Native focus** of a running instance isn't portable; the browser-surface
  fallback is the v1 behaviour.
