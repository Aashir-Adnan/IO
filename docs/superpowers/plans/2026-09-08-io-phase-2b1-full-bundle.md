# Phase 2B.1 — Full-Featured Bundle — Implementation Plan

> Follow-on to Phase 2B. REQUIRED SUB-SKILL: superpowers:executing-plans.

**Goal:** `IO.exe` on the Desktop that supports **every** feature — text, files,
media gallery, and **voice** — and is genuinely double-click-ready: it starts
its own Postgres container and migrates the schema on launch.

**Architecture:** (1) Drop the voice packages from `io.spec` `excludes` and add
the hooks / data collection they need (a local hook override fixes the broken
`hook-webrtcvad`). (2) A new `io_assistant/service/bootstrap.py` —
`ensure_database(config)` pings Postgres, runs `docker compose up -d db` from
the bundled compose file if it's down, waits for readiness, then
`alembic upgrade head`. `cli.run()` calls it before starting the service and
shows a pywebview error dialog if it can't (Docker not running, etc.).
(3) Rebuild, install the Desktop shortcut, verify end to end.

**Tech Stack:** PyInstaller, `pyinstaller-hooks-contrib`, `docker compose`
(the user already runs `pgvector/pgvector:pg16` this way), Alembic.

**Spec:** extends `docs/superpowers/specs/2026-09-08-io-phase-2-desktop-packaging-design.md`.

## Global Constraints

- local-first: the only bundled network behaviour is `docker compose up -d`
  against the local daemon + the sanctioned Anthropic backend.
- The bundle needs **Docker Desktop running**. That is the one prerequisite;
  everything else the exe handles. If Docker is absent/stopped the exe says so
  in a dialog and exits — it never silently half-starts.
- Models (Whisper / Piper voices) still download at first use to
  `~/.local/share/io/` — not bundled. The voice *code* (faster-whisper,
  piper-tts, sounddevice, webrtcvad) **is** bundled.
- Alembic migrations run on every launch (idempotent; `upgrade head`).
- Package `io_assistant`; tests via `IO_TEST_DATABASE_URL=… uv run pytest`.
- The PyInstaller build + the double-click check are manual (Windows, minutes);
  automated tests cover `bootstrap` logic and the spec's data list.

---

## Task 1: Voice packages in the bundle

**Files:**
- Create: `packaging/hooks/hook-webrtcvad.py` (override the broken contrib hook)
- Modify: `packaging/io.spec` (`excludes`, `hiddenimports`, `hookspath`,
  `collect_*` for native deps)
- Test: `tests/test_packaging_spec.py` (assert the voice modules are NOT in
  `excludes`)

**Interfaces:**
- Produces: `io.spec` `EXCLUDES: list[str]` (module-level, test-readable) no
  longer contains `webrtcvad` / `sounddevice` / `faster_whisper` / `piper` /
  `ctranslate2` / `onnxruntime`; `hookspath` includes `packaging/hooks`;
  `hiddenimports` covers the lazy voice imports.

- [ ] **Step 1: Write the failing test** — extend `tests/test_packaging_spec.py`

```python
def test_spec_bundles_voice():
    ns = runpy.run_path(str(ROOT / "packaging" / "io.spec"),
                        run_name="__spec_probe__")
    ex = set(ns["EXCLUDES"])
    for mod in ("webrtcvad", "sounddevice", "faster_whisper", "piper",
                "ctranslate2", "onnxruntime"):
        assert mod not in ex, f"{mod} is still excluded from the bundle"
    assert any("hooks" in p for p in ns["HOOKSPATH"])
```

- [ ] **Step 2: Run it** — `… uv run pytest tests/test_packaging_spec.py -q` →
  FAIL (`EXCLUDES` / `HOOKSPATH` not defined; voice still excluded).

- [ ] **Step 3: Local hook override** — `packaging/hooks/hook-webrtcvad.py`:

```python
# Override the pyinstaller-hooks-contrib meta-hook that fails to import on
# webrtcvad-wheels. webrtcvad is a single C extension with no data files.
hiddenimports = []
datas = []
binaries = []
```

- [ ] **Step 4: Rewrite the relevant parts of `io.spec`**

```python
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_data_files, collect_submodules

HOOKSPATH = [str(ROOT / "packaging" / "hooks")]

EXCLUDES = ["reportlab", "pytest", "pyinstaller", "torch"]

_VOICE_HIDDEN = [
    "webrtcvad", "sounddevice", "pynput", "pynput.keyboard", "pynput.mouse",
    "faster_whisper", "ctranslate2", "onnxruntime", "av",
    "piper", "piper.voice", "espeakng_loader",
]

if __name__ != "__spec_probe__":
    _binaries = collect_dynamic_libs("ctranslate2") + collect_dynamic_libs("onnxruntime") \
        + collect_dynamic_libs("_sounddevice_data") + collect_dynamic_libs("av")
    _datas = [(str(ROOT / s), d) for s, d in DATAS] \
        + collect_data_files("faster_whisper") \
        + collect_data_files("espeakng_loader") \
        + collect_data_files("piper") \
        + collect_data_files("_sounddevice_data")
    a = Analysis(
        [str(ROOT / ENTRY)],
        pathex=[str(ROOT)],
        binaries=_binaries,
        datas=_datas,
        hiddenimports=HIDDEN_IMPORTS + _VOICE_HIDDEN + collect_submodules("onnxruntime"),
        hookspath=HOOKSPATH,
        runtime_hooks=[],
        excludes=EXCLUDES,
        noarchive=False,
    )
    ...  # PYZ / EXE / COLLECT unchanged
```

Keep `ENTRY` / `DATAS` / `HIDDEN_IMPORTS` module-level as before; add
`EXCLUDES` / `HOOKSPATH` module-level too so the probe test reads them.

- [ ] **Step 5: Run the unit test** — `… uv run pytest tests/test_packaging_spec.py -q` → PASS.

- [ ] **Step 6: Commit**

```bash
git add packaging/hooks/hook-webrtcvad.py packaging/io.spec tests/test_packaging_spec.py
git commit -m "feat(packaging): bundle voice deps + local webrtcvad hook override"
```

---

## Task 2: `bootstrap.py` — DB up + migrate on launch

**Files:**
- Create: `io_assistant/service/bootstrap.py`
- Modify: `io_assistant/cli.py` (`run()` calls `ensure_database`; `serve()` too)
- Modify: `io_assistant/service/runner.py` (`open_window` gains an
  `error_dialog(msg)` helper the bootstrap failure uses)
- Modify: `packaging/io.spec` `DATAS` — add `docker-compose.yml`,
  `scripts/initdb`
- Test: `tests/test_bootstrap.py`

**Interfaces:**
- Consumes: `Config`, `config_source()` (Phase 2B).
- Produces:
  - `BootstrapError(Exception)` — carries a user-facing `.message`.
  - `db_reachable(config, timeout=1.0) -> bool` — a `psycopg` connect probe.
  - `project_root() -> Path` — the bundle dir when frozen (`sys._MEIPASS` /
    the exe's dir), else the repo root.
  - `ensure_database(config, *, start_container=True) -> None`:
    1. `db_reachable` → if yes, skip to migrate.
    2. else, if `start_container` and `docker` is on PATH → `docker compose -f
       <project_root>/docker-compose.yml up -d db`; poll `db_reachable` for
       ~60 s. If `docker` is missing → `raise BootstrapError("Docker Desktop
       isn't running. Start it and reopen IO.")`.
    3. `alembic upgrade head` against `config.database_url` (script location =
       `<project_root>/io_assistant/db/migrations`, `sqlalchemy.url` set
       explicitly) — reuses the pattern from `tests/conftest.py::_alembic_config`.
  - `cli.run()` / `cli.serve()`: wrap `ensure_database(load_config())` in
    `try/except BootstrapError` → `run()` shows `runner.error_dialog(e.message)`
    and exits 1; `serve()` prints it and exits 1.
  - `runner.error_dialog(message: str) -> None` — pywebview
    `create_window("IO", html=…)` one-liner, or a `print` fallback when webview
    is unavailable.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bootstrap.py
import pytest
from tests.conftest import requires_db
from io_assistant.service.bootstrap import (
    ensure_database, db_reachable, BootstrapError)


@requires_db
def test_db_reachable_true(config):
    config.database_url = __import__("os").environ["IO_TEST_DATABASE_URL"]
    assert db_reachable(config) is True


@requires_db
def test_ensure_database_migrates_when_reachable(config, monkeypatch):
    config.database_url = __import__("os").environ["IO_TEST_DATABASE_URL"]
    calls = []
    monkeypatch.setattr("io_assistant.service.bootstrap._alembic_upgrade",
                        lambda cfg: calls.append("migrate"))
    ensure_database(config, start_container=False)
    assert calls == ["migrate"]


def test_ensure_database_no_docker_raises(config, monkeypatch):
    config.database_url = "postgresql+psycopg://io:io@127.0.0.1:59998/none"
    monkeypatch.setattr("io_assistant.service.bootstrap.db_reachable",
                        lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(BootstrapError) as e:
        ensure_database(config)
    assert "docker" in str(e.value).lower()
```

- [ ] **Step 2: Run it** → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `bootstrap.py`**

```python
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from io_assistant.config import Config

__all__ = ["BootstrapError", "db_reachable", "ensure_database", "project_root"]


class BootstrapError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def db_reachable(config: Config, timeout: float = 1.0) -> bool:
    try:
        import psycopg

        with psycopg.connect(_dsn(config.database_url), connect_timeout=int(timeout) or 1):
            return True
    except Exception:
        return False


def _alembic_upgrade(config: Config) -> None:
    from alembic import command
    from alembic.config import Config as AlembicConfig

    root = project_root()
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "io_assistant" / "db" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", config.database_url)
    command.upgrade(cfg, "head")


def ensure_database(config: Config, *, start_container: bool = True) -> None:
    if not db_reachable(config):
        if not start_container:
            raise BootstrapError("Database is not reachable.")
        if shutil.which("docker") is None:
            raise BootstrapError(
                "Docker Desktop isn't running. Start Docker Desktop, then reopen IO.")
        compose = project_root() / "docker-compose.yml"
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(compose), "up", "-d", "db"],
                check=True, capture_output=True, text=True, timeout=120)
        except Exception as e:  # noqa: BLE001
            raise BootstrapError(
                f"Couldn't start the database container.\n{e}") from e
        for _ in range(60):
            if db_reachable(config):
                break
            time.sleep(1)
        else:
            raise BootstrapError("The database container did not become ready.")
    _alembic_upgrade(config)
```

- [ ] **Step 4: `runner.error_dialog` + `cli` wiring**

`runner.py`:
```python
def error_dialog(message: str) -> None:
    try:
        import webview

        webview.create_window("IO — can't start", html=(
            f"<body style='font:15px system-ui;padding:28px;color:#222'>"
            f"<h2>IO can't start</h2><p>{message}</p></body>"))
        webview.start()
    except Exception:
        print(message)
```

`cli.run()` — after `config = load_config()` and the single-instance guard,
before opening the window:
```python
        from io_assistant.service.bootstrap import BootstrapError, ensure_database
        try:
            ensure_database(config)
        except BootstrapError as e:
            from io_assistant.service.runner import error_dialog
            error_dialog(e.message)
            raise SystemExit(1)
```
`cli.serve()` — same, but `print(e.message); raise typer.Exit(1)`.

- [ ] **Step 5: `io.spec` DATAS** — add:
```python
    ("docker-compose.yml", "."),
    ("scripts/initdb", "scripts/initdb"),
```

- [ ] **Step 6: Run the tests** — `… uv run pytest tests/test_bootstrap.py tests/test_cli_serve.py -q` → PASS.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/service/bootstrap.py io_assistant/service/runner.py \
  io_assistant/cli.py packaging/io.spec tests/test_bootstrap.py
git commit -m "feat(packaging): ensure_database — start DB container + migrate on launch"
```

---

## Task 3: Build, install to Desktop, verify

**Files:** none (build + manual verification); record results in the commit.

- [ ] **Step 1: Full unit suite** — `… uv run pytest -q -p no:warnings` → PASS
  (Phase 2B's 298 + `test_bootstrap` + the spec-test additions).

- [ ] **Step 2: Build** — `.\dev.ps1 build`
  Expected: `dist/IO/IO.exe` produced. If PyInstaller reports a missing module
  at build time, add it to `_VOICE_HIDDEN` / `HIDDEN_IMPORTS` and rebuild.
  Note the bundle size (voice deps ≈ +300–500 MB).

- [ ] **Step 3: Runtime check** — `.\dev.ps1 down` (stop the dev stack so the
  exe does the bootstrap itself), then double-click `dist\IO\IO.exe`:
  - the DB container comes up, migrations run, the window opens (fullscreen).
  - `curl http://127.0.0.1:8765/health` → `{"ok": true, ...}`.
  - `curl http://127.0.0.1:8765/voice/health` → `whisper`/`piper` reflect
    whether the models are downloaded (the *code* being present is the win;
    first real use downloads the model).
  - launch `IO.exe` again → it opens `/app/` in the browser and exits (no
    second window).
  Fix any import error by adding the module to the spec and rebuilding.

- [ ] **Step 4: Install the shortcut** — `.\dev.ps1 install`
  Expected: `Desktop\IO.lnk` → `dist\IO\IO.exe` with the IO icon.

- [ ] **Step 5: Commit** the outcome

```bash
git commit --allow-empty -m "build: full-featured IO.exe verified (voice + DB bootstrap), Desktop shortcut installed"
```

---

## Task 4: Docs + state

- [ ] **Step 1:** `.claude/knowledge/desktop-app.md` — update the Packaging
  section: voice is now bundled (models still download on first use); the exe
  starts its own `pgvector/pgvector:pg16` container and runs `alembic upgrade
  head` on launch via `io_assistant/service/bootstrap.py`; the one prerequisite
  is Docker Desktop running; a pywebview dialog explains a failed bootstrap.
- [ ] **Step 2:** `.claude/skills/run-local.md` — note `dev.ps1 down` before
  double-clicking `IO.exe` if you want to see it do its own bootstrap.
- [ ] **Step 3:** `.claude/state/` — move Phase 2B.1 to `completed.md`; update
  `session.md` (bundle is full-featured + on the Desktop; remaining is the
  open-source-readiness track).
- [ ] **Step 4:** full suite green → commit.

```bash
git add .claude/ && git commit -m "docs+state: full-featured bundle"
```

---

## Self-Review

- **Voice bundle size** — accepted; a local desktop assistant with offline STT
  is inherently large. torch stays excluded (faster-whisper uses ctranslate2,
  not torch).
- **`hook-webrtcvad` override** — the contrib meta-hook fails on
  `webrtcvad-wheels`; a local no-op hook on `hookspath` (which wins) is the
  standard fix. If a future hooks-contrib fixes it, the override is harmless.
- **Docker requirement** — documented as the single prerequisite; the failure
  path is a clear dialog, never a half-start. Bundling an embedded PostgreSQL
  is out of scope (backlog).
- **Migrations every launch** — `upgrade head` is idempotent and fast when
  there's nothing to do.
- **`project_root()` when frozen** — one-dir bundle: data sits next to the exe
  (`_internal/`); `sys._MEIPASS` points there. `docker-compose.yml` and
  `scripts/initdb` are bundled relative to it.
- Type consistency: `ensure_database(config, *, start_container=True)`,
  `db_reachable(config, timeout=1.0)`, `BootstrapError.message`,
  `project_root() -> Path`, `_alembic_upgrade(config)` — all used consistently
  across `bootstrap.py`, `cli.py`, and the tests.
