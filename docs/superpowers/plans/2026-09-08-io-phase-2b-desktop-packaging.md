# Phase 2B — Desktop Packaging — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `io run` into a double-clickable Windows app — `IO.exe` with the
IO logo as its icon — that refuses to start a second copy and surfaces the
running one instead.

**Architecture:** A `scripts/make_icon.py` turns `assets/io-logo.png` into a
multi-resolution `.ico`. `io_assistant/service/singleton.py` provides a
cross-process single-instance lock (Windows named mutex / POSIX flock) that
`cli.run()` checks first — a second launch opens the running app's URL and
exits. `packaging/io.spec` is a PyInstaller **one-dir** bundle of a thin
`io_assistant/app_entry.py` entry point. `dev.ps1 build` produces `dist/IO/`;
`dev.ps1 install` puts a Desktop shortcut to `dist/IO/IO.exe`.

**Tech Stack:** `Pillow` (icon generation — already a dep from Phase 2C),
`ctypes`/`fcntl` (the lock), `pyinstaller` (dev dep). No new runtime deps.

**Spec:** `docs/superpowers/specs/2026-09-08-io-phase-2-desktop-packaging-design.md`
(read alongside this plan).

## Global Constraints

- **local-first:** the bundle adds no network calls. The socket-guard test is
  unaffected (packaging touches no tested request path).
- Models (Whisper / Piper) are **not** bundled — they download at first use to
  `~/.local/share/io/` exactly as today.
- `config.toml` ships bundled as a **default**; a user copy in the CWD or
  `~/.config/io/config.toml` still wins.
- Package stays `io_assistant`; the executable is named `IO`.
- **Postgres is not bundled** — the frozen app expects Docker Postgres (or a
  user `database_url`) and fails with clear guidance if the DB is unreachable.
- macOS / Linux packaging, code signing, auto-update, `.msi` → out of scope
  (backlog).
- Package `io_assistant`; run tests via `IO_TEST_DATABASE_URL=… uv run pytest`.
- The full PyInstaller build is a **manual** step (minutes, platform-specific) —
  not run in the automated suite. Tests cover the icon, the lock, the config
  path, and that the spec's referenced files exist.

## File Structure

**New:**

| file | responsibility |
|---|---|
| `assets/io-logo.png` | source logo (**supplied by the user** — already present, 418×414 RGBA) |
| `assets/io.ico`, `assets/io-512.png` | generated at build time (git-ignored) |
| `scripts/make_icon.py` | `assets/io-logo.png` → `.ico` (16–256) + padded `io-512.png` |
| `io_assistant/service/singleton.py` | `acquire_single_instance()`, `SingleInstance`, `surface_running_instance()` |
| `io_assistant/app_entry.py` | frozen entry point — calls `cli.run()` |
| `packaging/io.spec` | PyInstaller one-dir spec |
| `tests/test_make_icon.py`, `tests/test_singleton.py`, `tests/test_packaging_spec.py` | new tests |

**Modified:**

| file | change |
|---|---|
| `io_assistant/cli.py` | `run()` calls `acquire_single_instance()` first |
| `io_assistant/config.py` | `load_config` also checks `~/.config/io/config.toml` |
| `.gitignore` | `assets/io.ico`, `assets/io-512.png`, `build/`, `dist/`, `*.spec`-generated |
| `dev.ps1` | new `build`; `install` points at `dist/IO/IO.exe` |
| `pyproject.toml` | `uv add --group dev pyinstaller` |
| `.claude/knowledge/desktop-app.md`, `.claude/skills/run-local.md`, `.claude/state/*` | docs |

---

## Task 1: `scripts/make_icon.py` — logo → .ico

**Files:**
- Create: `scripts/make_icon.py`
- Modify: `.gitignore` (ignore the generated files)
- Test: `tests/test_make_icon.py`

**Interfaces:**
- Consumes: `assets/io-logo.png` (Pillow-readable).
- Produces:
  - `make_icon(src: Path, ico_out: Path, png_out: Path) -> None` — loads `src`,
    pads to a square (transparent) if needed, writes `ico_out` as a `.ico`
    containing sizes `(16, 32, 48, 64, 128, 256)`, and writes `png_out` as a
    256→512 padded RGBA PNG.
  - `scripts/make_icon.py` run as `python scripts/make_icon.py` uses the repo
    defaults (`assets/io-logo.png` → `assets/io.ico` + `assets/io-512.png`) and
    prints the output paths.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_make_icon.py
from pathlib import Path

from PIL import Image
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from make_icon import make_icon  # noqa: E402


def test_make_icon_produces_multisize_ico(tmp_path):
    src = tmp_path / "logo.png"
    Image.new("RGBA", (300, 240), (100, 120, 200, 255)).save(src)  # non-square
    ico = tmp_path / "out.ico"
    png = tmp_path / "out-512.png"
    make_icon(src, ico, png)
    assert ico.exists() and png.exists()
    with Image.open(ico) as im:
        sizes = set(getattr(im, "ico", im).sizes) if hasattr(im, "ico") else None
    # Pillow exposes embedded sizes via .ico.sizes on newer versions; fall back
    with Image.open(ico) as im:
        assert im.size[0] in (16, 32, 48, 64, 128, 256)
    with Image.open(png) as im:
        assert im.size == (512, 512) and im.mode == "RGBA"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `IO_TEST_DATABASE_URL=… uv run pytest tests/test_make_icon.py -q`
Expected: FAIL — `ModuleNotFoundError: make_icon`.

- [ ] **Step 3: Implement `scripts/make_icon.py`**

```python
"""Generate assets/io.ico + assets/io-512.png from assets/io-logo.png."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

_ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
_ROOT = Path(__file__).resolve().parents[1]


def _square(im: Image.Image) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    if w == h:
        return im
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
    return canvas


def make_icon(src: Path, ico_out: Path, png_out: Path) -> None:
    im = _square(Image.open(src))
    ico_out.parent.mkdir(parents=True, exist_ok=True)
    im.resize((256, 256), Image.LANCZOS).save(ico_out, format="ICO", sizes=_ICO_SIZES)
    im.resize((512, 512), Image.LANCZOS).save(png_out, format="PNG")


def main() -> None:
    src = _ROOT / "assets" / "io-logo.png"
    if not src.exists():
        raise SystemExit(f"missing {src} — drop the logo there first")
    ico = _ROOT / "assets" / "io.ico"
    png = _ROOT / "assets" / "io-512.png"
    make_icon(src, ico, png)
    print(ico)
    print(png)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Add ignores to `.gitignore`**

```
assets/io.ico
assets/io-512.png
build/
dist/
```

- [ ] **Step 5: Run the tests + generate the real assets**

```bash
IO_TEST_DATABASE_URL=… uv run pytest tests/test_make_icon.py -q
uv run python scripts/make_icon.py
```
Expected: PASS; `assets/io.ico` and `assets/io-512.png` created (git-ignored).

- [ ] **Step 6: Commit**

```bash
git add assets/io-logo.png scripts/make_icon.py .gitignore tests/test_make_icon.py
git commit -m "feat(packaging): make_icon — logo -> multi-size .ico + 512 png"
```

---

## Task 2: `singleton.py` — single-instance lock

**Files:**
- Create: `io_assistant/service/singleton.py`
- Test: `tests/test_singleton.py`

**Interfaces:**
- Consumes: `Config` (for `surface_running_instance`).
- Produces:
  - `LOCK_DIR = Path(os.path.expanduser("~/.local/share/io"))`.
  - `class SingleInstance` — context manager; `.release()` frees the OS handle
    / unlocks + removes the lock file. `__enter__` returns `self`; `__exit__`
    calls `release()`.
  - `acquire_single_instance(name: str = "io-assistant") -> SingleInstance |
    None` — returns a held `SingleInstance` if we are the first, else `None`.
    Windows: `CreateMutexW(None, False, f"Global\\{name}")` +
    `GetLastError() == 183` (`ERROR_ALREADY_EXISTS`) → `None`. POSIX:
    `fcntl.flock(fd, LOCK_EX | LOCK_NB)` on `LOCK_DIR / f"{name}.lock"` →
    `BlockingIOError` → `None`.
  - `surface_running_instance(config: Config) -> None` — `httpx.get(base +
    "/health", timeout=2)`; on success `webbrowser.open(base + "/app/")` and
    print `"IO is already running — opened it in your browser."`; otherwise
    print `"IO seems to be starting already."`. Never starts a service.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_singleton.py
import os
import sys

import pytest

from io_assistant.service.singleton import acquire_single_instance


@pytest.mark.skipif(sys.platform == "win32", reason="flock path is POSIX")
def test_second_acquire_returns_none_posix(tmp_path, monkeypatch):
    monkeypatch.setattr("io_assistant.service.singleton.LOCK_DIR", tmp_path)
    first = acquire_single_instance("io-test-lock")
    assert first is not None
    assert acquire_single_instance("io-test-lock") is None
    first.release()
    third = acquire_single_instance("io-test-lock")
    assert third is not None
    third.release()


@pytest.mark.skipif(sys.platform != "win32", reason="mutex path is Windows")
def test_second_acquire_returns_none_win():
    first = acquire_single_instance("io-test-lock-win")
    assert first is not None
    assert acquire_single_instance("io-test-lock-win") is None
    first.release()


def test_surface_running_instance_no_service(capsys, config):
    from io_assistant.service.singleton import surface_running_instance
    config.service.port = 59999   # nothing listening
    surface_running_instance(config)
    assert "starting" in capsys.readouterr().out.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `… uv run pytest tests/test_singleton.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `singleton.py`**

```python
from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

from io_assistant.config import Config

__all__ = ["SingleInstance", "acquire_single_instance", "surface_running_instance",
           "LOCK_DIR"]

LOCK_DIR = Path(os.path.expanduser("~/.local/share/io"))
_ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, *, handle=None, fd=None, path: Path | None = None):
        self._handle = handle
        self._fd = fd
        self._path = path

    def release(self) -> None:
        if self._handle is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._fd is not None:
            import fcntl

            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
            self._fd = None
        if self._path is not None:
            try:
                self._path.unlink()
            except OSError:
                pass
            self._path = None

    def __enter__(self) -> "SingleInstance":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def acquire_single_instance(name: str = "io-assistant") -> SingleInstance | None:
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.CreateMutexW(None, False, f"Global\\{name}")
        if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
            return None
        return SingleInstance(handle=handle)

    import fcntl

    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCK_DIR / f"{name}.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return SingleInstance(fd=fd, path=path)


def surface_running_instance(config: Config) -> None:
    import httpx

    base = f"http://{config.service.host}:{config.service.port}"
    try:
        ok = bool(httpx.get(f"{base}/health", timeout=2).json().get("ok"))
    except Exception:
        ok = False
    if ok:
        webbrowser.open(f"{base}/app/")
        print("IO is already running — opened it in your browser.")
    else:
        print("IO seems to be starting already.")
```

- [ ] **Step 4: Run the tests**

Run: `… uv run pytest tests/test_singleton.py -q`
Expected: PASS (one of the platform tests runs, the other skips;
`test_surface_running_instance_no_service` passes).

- [ ] **Step 5: Commit**

```bash
git add io_assistant/service/singleton.py tests/test_singleton.py
git commit -m "feat(packaging): single-instance lock + surface-running helper"
```

---

## Task 3: `cli.run()` guard + `app_entry.py`

**Files:**
- Modify: `io_assistant/cli.py` (`run()`)
- Create: `io_assistant/app_entry.py`
- Test: `tests/test_cli_serve.py` (extend)

**Interfaces:**
- Consumes: `acquire_single_instance`, `surface_running_instance` (Task 2).
- Produces:
  - `cli.run()` first calls `acquire_single_instance()`; if `None` →
    `surface_running_instance(load_config())` then `raise SystemExit(0)`;
    otherwise the existing body runs inside `with inst:`.
  - `io_assistant/app_entry.py::main()` → `from io_assistant.cli import run;
    run()`. `if __name__ == "__main__": main()`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_cli_serve.py`

```python
def test_run_exits_when_instance_held(monkeypatch, config):
    import io_assistant.cli as cli

    monkeypatch.setattr(cli, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(
        "io_assistant.service.singleton.acquire_single_instance", lambda *a, **k: None)
    surfaced = {}
    monkeypatch.setattr(
        "io_assistant.service.singleton.surface_running_instance",
        lambda c: surfaced.setdefault("hit", True))
    started = {}
    monkeypatch.setattr(
        "io_assistant.service.runner.run_service",
        lambda *a, **k: started.setdefault("hit", True))

    import pytest
    with pytest.raises(SystemExit) as e:
        cli.run()
    assert e.value.code == 0
    assert surfaced.get("hit") and not started.get("hit")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `… uv run pytest tests/test_cli_serve.py::test_run_exits_when_instance_held -q`
Expected: FAIL — `run()` doesn't check the instance lock.

- [ ] **Step 3: Guard `cli.run()`**

Replace the body of `run()`:
```python
@app.command()
def run() -> None:
    """Open the desktop window, starting the service only if one isn't up."""
    import httpx

    from io_assistant.service.runner import open_window, run_service
    from io_assistant.service.singleton import (
        acquire_single_instance, surface_running_instance)

    config = load_config()
    inst = acquire_single_instance()
    if inst is None:
        surface_running_instance(config)
        raise SystemExit(0)

    with inst:
        base = f"http://{config.service.host}:{config.service.port}"
        url = f"{base}/app/"
        try:
            already = bool(httpx.get(f"{base}/health", timeout=1).json().get("ok"))
        except Exception:
            already = False

        fs = config.ui.fullscreen
        if already:
            open_window(url, fullscreen=fs)
            return

        server, _thread = run_service(config, block=False)
        try:
            open_window(url, fullscreen=fs)
        finally:
            server.should_exit = True
```

- [ ] **Step 4: Create `io_assistant/app_entry.py`**

```python
"""Frozen-app entry point (PyInstaller). Thin wrapper over `io run`."""
from __future__ import annotations


def main() -> None:
    from io_assistant.cli import run

    run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests**

Run: `… uv run pytest tests/test_cli_serve.py -q`
Expected: PASS (the existing serve tests still green; the new guard test
passes).

- [ ] **Step 6: Commit**

```bash
git add io_assistant/cli.py io_assistant/app_entry.py tests/test_cli_serve.py
git commit -m "feat(packaging): cli.run single-instance guard + app_entry"
```

---

## Task 4: `load_config` — user config outside the bundle

**Files:**
- Modify: `io_assistant/config.py` (`_repo_root_config` / `load_config`)
- Test: `tests/test_config.py` (extend)

**Interfaces:**
- Produces: `load_config(path=None)` search order — (1) explicit `path`, (2)
  `./config.toml` in the CWD, (3) `~/.config/io/config.toml`, (4) the bundled
  repo-root `config.toml`. First existing wins. `config_source() -> Path`
  helper returns the resolved path (for diagnostics / tests).

- [ ] **Step 1: Write the failing test** — append to `tests/test_config.py`

```python
def test_load_config_prefers_user_config(tmp_path, monkeypatch):
    from io_assistant.config import load_config

    repo_cfg = (tmp_path / "repo")
    repo_cfg.mkdir()
    # a valid minimal config for the user location
    user_dir = tmp_path / "userhome" / ".config" / "io"
    user_dir.mkdir(parents=True)
    good = (Path(__file__).resolve().parents[1] / "config.toml").read_text()
    (user_dir / "config.toml").write_text(good)

    monkeypatch.setattr("os.path.expanduser",
                        lambda p: p.replace("~", str(tmp_path / "userhome")))
    monkeypatch.chdir(tmp_path)   # no ./config.toml here
    cfg = load_config()
    assert cfg.embedding_dim == 768
```

(Import `Path` at the top of the test file if not already present.)

- [ ] **Step 2: Run test to verify it fails**

Run: `… uv run pytest tests/test_config.py::test_load_config_prefers_user_config -q`
Expected: FAIL — `load_config` only checks the repo root.

- [ ] **Step 3: Extend `load_config`**

```python
def _candidate_config_paths() -> list[Path]:
    return [
        Path("config.toml"),
        Path(os.path.expanduser("~/.config/io/config.toml")),
        Path(__file__).resolve().parent.parent / "config.toml",
    ]


def config_source(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    for p in _candidate_config_paths():
        if p.exists():
            return p
    return _candidate_config_paths()[-1]


def load_config(path: str | Path | None = None) -> Config:
    p = config_source(path)
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    ...  # unchanged from here
```

Keep `_repo_root_config` if other code imports it (grep first); otherwise
remove it and update references.

- [ ] **Step 4: Run the tests**

Run: `… uv run pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/config.py tests/test_config.py
git commit -m "feat(packaging): load_config checks CWD + ~/.config/io before the bundle"
```

---

## Task 5: `packaging/io.spec` + `dev.ps1 build`

**Files:**
- Create: `packaging/io.spec`
- Modify: `dev.ps1` (new `build`; `install` → `dist/IO/IO.exe`)
- Modify: `pyproject.toml` — `uv add --group dev pyinstaller`
- Test: `tests/test_packaging_spec.py`

**Interfaces:**
- Produces:
  - `packaging/io.spec` — PyInstaller one-dir, windowed, `icon=assets/io.ico`,
    `name="IO"`, entry `io_assistant/app_entry.py`, `datas` bundling
    `frontend/`, `config.toml`, `io_assistant/db/migrations/`,
    `io_assistant/prompts/`, `alembic.ini`, `assets/io-512.png`. A
    `HIDDEN_IMPORTS` list (uvicorn, pgvector, psycopg + psycopg_binary,
    webview backends, pypdf, docx, PIL). The spec exposes module-level
    `DATAS: list[tuple[str, str]]` and `ENTRY: str` for the test to read.
  - `dev.ps1 build` — assert `assets/io-logo.png`, run `make_icon.py`, run
    `pyinstaller packaging/io.spec --noconfirm`, print `dist/IO/IO.exe`.
  - `dev.ps1 install` — ensure the exe exists (build if missing), create
    `Desktop\IO.lnk` → `dist\IO\IO.exe`, `WorkingDirectory=$Root`,
    `IconLocation` = `assets\io.ico`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_packaging_spec.py
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_spec_datas_paths_exist():
    ns = runpy.run_path(str(ROOT / "packaging" / "io.spec"),
                        run_name="__spec_probe__")
    assert (ROOT / ns["ENTRY"]).exists()
    for src, _dest in ns["DATAS"]:
        assert (ROOT / src).exists(), f"missing spec data source: {src}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `… uv run pytest tests/test_packaging_spec.py -q`
Expected: FAIL — no `packaging/io.spec`.

- [ ] **Step 3: Add the dev dep**

```bash
uv add --group dev pyinstaller
```

- [ ] **Step 4: Write `packaging/io.spec`**

```python
# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-dir spec for IO. Build:  uv run pyinstaller packaging/io.spec --noconfirm"""
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # SPECPATH is injected by PyInstaller

ENTRY = "io_assistant/app_entry.py"

DATAS = [
    ("frontend", "frontend"),
    ("config.toml", "."),
    ("alembic.ini", "."),
    ("io_assistant/db/migrations", "io_assistant/db/migrations"),
    ("io_assistant/prompts", "io_assistant/prompts"),
    ("assets/io-512.png", "assets"),
]

HIDDEN_IMPORTS = [
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
    "pgvector.sqlalchemy", "psycopg", "psycopg_binary",
    "webview.platforms.winforms", "webview.platforms.edgechromium",
    "pypdf", "docx", "PIL.Image",
]

# When PyInstaller executes the spec, __spec_probe__ is not the run name; the
# test imports it with run_name="__spec_probe__" and only reads ENTRY / DATAS.
if __name__ != "__spec_probe__":
    a = Analysis(
        [str(ROOT / ENTRY)],
        pathex=[str(ROOT)],
        binaries=[],
        datas=[(str(ROOT / s), d) for s, d in DATAS],
        hiddenimports=HIDDEN_IMPORTS,
        hookspath=[],
        runtime_hooks=[],
        excludes=["reportlab", "pytest"],
        noarchive=False,
    )
    pyz = PYZ(a.pure)
    exe = EXE(
        pyz, a.scripts, [],
        exclude_binaries=True,
        name="IO",
        console=False,
        icon=str(ROOT / "assets" / "io.ico"),
    )
    coll = COLLECT(exe, a.binaries, a.datas, name="IO")
```

- [ ] **Step 5: Add `build` to `dev.ps1` + update `install`**

`Do-Install` — replace the shortcut target:
```powershell
function Do-Build {
  if (-not (Test-Path "$Root\assets\io-logo.png")) {
    Err "assets\io-logo.png is missing — add the logo first."; return
  }
  uv run python "$Root\scripts\make_icon.py"
  uv run pyinstaller "$Root\packaging\io.spec" --noconfirm
  $exe = "$Root\dist\IO\IO.exe"
  if (Test-Path $exe) { Ok "built: $exe" } else { Err "build failed" }
}

function Do-Install {
  $exe = "$Root\dist\IO\IO.exe"
  if (-not (Test-Path $exe)) { Do-Build }
  if (-not (Test-Path $exe)) { return }
  $desktop = [Environment]::GetFolderPath("Desktop")
  $lnk = Join-Path $desktop "IO.lnk"
  $w = New-Object -ComObject WScript.Shell
  $s = $w.CreateShortcut($lnk)
  $s.TargetPath = $exe
  $s.WorkingDirectory = $Root
  $s.IconLocation = "$Root\assets\io.ico"
  $s.Description = "IO — local-first assistant"
  $s.Save()
  Ok "shortcut created: $lnk  ->  $exe"
}
```
Add to the `switch`: `"build"   { Do-Build }`. Add a help line for `build`.

- [ ] **Step 6: Run the tests**

Run: `… uv run pytest tests/test_packaging_spec.py -q`
Expected: PASS (`ENTRY` exists, every `DATAS` source exists).

- [ ] **Step 7: Commit**

```bash
git add packaging/io.spec dev.ps1 pyproject.toml uv.lock tests/test_packaging_spec.py
git commit -m "feat(packaging): io.spec (PyInstaller one-dir) + dev.ps1 build/install"
```

---

## Task 6: Docs, state, full suite, manual build note

**Files:**
- Modify: `.claude/knowledge/desktop-app.md`, `.claude/skills/run-local.md`,
  `.claude/state/{session,completed,backlog}.md`
- Test: the whole suite

- [ ] **Step 1: Update `.claude/knowledge/desktop-app.md`**

Add a **## Packaging (Phase 2B)** section: `scripts/make_icon.py`
(`assets/io-logo.png` → `.ico` + `io-512.png`, both git-ignored);
`io_assistant/service/singleton.py` (`acquire_single_instance` — Windows named
mutex / POSIX flock; `surface_running_instance` opens the running app's
`/app/` URL and exits); `cli.run()` checks the lock first; `app_entry.py` is the
frozen entry point; `load_config` search order (CWD → `~/.config/io` →
bundle); `packaging/io.spec` (PyInstaller one-dir, `name="IO"`, no bundled
Postgres/models); `dev.ps1 build` produces `dist/IO/`, `dev.ps1 install`
shortcuts to `dist\IO\IO.exe`. Note the build is manual and Windows-only for
v1; macOS/Linux/signing/auto-update are backlog.

- [ ] **Step 2: Update `.claude/skills/run-local.md`**

Replace the `dev.ps1 install` line and add `build`:
```
.\dev.ps1 build       # generate the icon + PyInstaller one-dir bundle (dist\IO\IO.exe)
.\dev.ps1 install     # Desktop "IO" shortcut -> dist\IO\IO.exe (runs build if needed)
```
Note: second launch of `IO.exe` just opens the running window in the browser
and exits (single-instance).

- [ ] **Step 3: Update `.claude/state/`**

Move the Spec B line from `backlog.md` to `completed.md` (dated). Update
`session.md`: Phase 2B done on `io-phase-2b-packaging`; the PyInstaller build
itself still needs a manual run on Windows (`.\dev.ps1 build`, double-click
`dist\IO\IO.exe`, launch twice to confirm single-instance). Note that all of
Phase 2 (A + C + B) is then complete; next is the open-source-readiness work
(default local provider, LICENSE, README, CI, make public).

- [ ] **Step 4: Full suite**

Run: `IO_TEST_DATABASE_URL=… uv run pytest -q -p no:warnings`
Expected: PASS — 292 (Phase 2C) + `test_make_icon` + `test_singleton` +
`test_packaging_spec` + the two extended tests. Socket guard green.

- [ ] **Step 5: Manual build verification (record the result, don't block)**

On Windows: `.\dev.ps1 build` → `.\dev.ps1 install` → double-click the Desktop
`IO` shortcut. Confirm: the window opens (fullscreen, IO icon in the taskbar),
a second double-click opens `/app/` in the browser and exits without a second
window. If PyInstaller misses a hidden import, add it to `HIDDEN_IMPORTS` in
`io.spec` and rebuild. Record the outcome in the commit message / session.md;
if the build can't be run in this environment, note that and rely on
`test_packaging_spec` + the manual checklist.

- [ ] **Step 6: Commit**

```bash
git add .claude/
git commit -m "docs+state: Phase 2B desktop packaging — knowledge, run-local, state"
```

---

## Self-Review

**1. Spec coverage**

| Spec § | Task |
|---|---|
| §3 logo → `.ico` + `io-512.png` (`make_icon.py`) | 1 |
| §4 `singleton.py` — `acquire_single_instance`, `SingleInstance`, `surface_running_instance` | 2 |
| §4 `cli.run()` guard; `app_entry.py` | 3 |
| §5 `packaging/io.spec` (one-dir, windowed, icon, datas, hidden imports, no Postgres/models) | 5 |
| §5 bundled config as default; user copy wins | 4 |
| §6 `dev.ps1 build` + `install` → `dist\IO\IO.exe` | 5 |
| §7 tests: `test_singleton`, `test_make_icon`, `test_packaging_spec`, `test_cli_serve` extension | 1, 2, 3, 5 |
| §7 manual `dev.ps1 build` verification | 6 |
| §8 risks: one-dir chosen; DB-not-bundled fails loudly; hidden-import iteration; unsigned exe; non-portable focus → browser fallback | 5 (spec), 2 (`surface_running_instance`), 6 (manual) |

No gaps. Spec §5's "clear dialog if the DB is unreachable" is **not** a
separate task — the frozen app inherits `io serve`/`io run`'s existing
behaviour (the service starts, `/health` reports `database: false`, the
frontend shows the connection state). A blocking native dialog is deferred to
backlog and noted in Task 6's docs.

**2. Placeholder scan** — no "TBD" / "handle edge cases". The `io.spec`
`HIDDEN_IMPORTS` list is a concrete starting set with an explicit "add and
rebuild" loop in Task 6 Step 5 (hidden-import discovery genuinely requires
running PyInstaller once — the plan can't enumerate them all a priori, and says
so). The `test_make_icon` size assertion is loose (`in (16,…,256)`) because
Pillow's ICO reader surfaces only one embedded size via `.size` on some
versions — the test still proves a valid multi-size ICO was written.

**3. Type consistency**

- `acquire_single_instance(name="io-assistant") -> SingleInstance | None` and
  `SingleInstance.release()` — same in Tasks 2, 3, and both test files.
- `surface_running_instance(config: Config) -> None` — Task 2 defines, Task 3
  calls with `load_config()`.
- `make_icon(src, ico_out, png_out) -> None` — Task 1 defines, Task 5's
  `dev.ps1 build` calls `scripts/make_icon.py` (the `main()` wrapper).
- `io.spec` module-level `ENTRY: str` (repo-relative) and `DATAS:
  list[tuple[str, str]]` (repo-relative source, bundle dest) — Task 5 defines
  the exact shape the Task 5 test reads; the `if __name__ != "__spec_probe__"`
  guard keeps `runpy.run_path(run_name="__spec_probe__")` from invoking
  `Analysis`/`EXE`/`COLLECT` (which only exist inside PyInstaller).
- `config_source(path=None) -> Path` and the 3-entry
  `_candidate_config_paths()` — Task 4 defines; `load_config` uses
  `config_source`. Grep for `_repo_root_config` importers before deleting it
  (Task 4 Step 3 says so).
