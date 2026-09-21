# Self-update Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development). Steps use checkbox syntax.

**Goal:** IO checks its GitHub remote for new commits, offers the update in the UI, and on approval pulls, rebuilds and relaunches while keeping data and settings.

**Architecture:** Plain `git` (fetch/rev-list/log) in a small `io_assistant/updates/` package, no GitHub API and no stored token. A background `UpdateChecker` caches the last status; two service endpoints expose it. Applying spawns a detached `scripts/update.ps1` (a running process can't replace its own venv/exe) that snapshots the DB, pulls fast-forward only, `uv sync`s, rebuilds the exe if one exists, and relaunches. User settings survive via a gitignored `config.local.toml` deep-merged over `config.toml`.

**Tech Stack:** Python 3.11 (`subprocess`, `tomllib`), FastAPI, vanilla ES-module frontend, PowerShell, pytest against real temporary git repos.

**Spec:** `docs/superpowers/specs/2026-09-21-self-update-design.md`

## Global Constraints

- Local-first: the only new outbound call is `git fetch` to the configured remote, only when `[updates].enabled`. Never auto-applied. Set `GIT_TERMINAL_PROMPT=0` so a credential prompt can never hang IO.
- Never mock git: tests use real temp repos (bare remote + clone). Never mock the DB (this feature needs none).
- Everything through `uv run`. Test command: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run pytest -q -p no:warnings`.
- Deviation from spec: `[updates].branch = ""` means "the branch currently checked out" (default), not `"main"`; a branch with no remote counterpart reports "no update".
- No git/network work inside tests' `create_app` unless the test starts it: the checker thread starts only when `create_app` owns its engine (production), same guard as the embedding backfiller.

## File structure

| File | Responsibility |
|---|---|
| `io_assistant/config.py` (modify) | `UpdatesConfig`; `load_config` merges `config.local.toml` |
| `io_assistant/updates/__init__.py`, `check.py` (create) | `UpdateStatus`, `find_repo`, `check` |
| `io_assistant/updates/localize.py` (create) | one-time move of user edits into `config.local.toml` |
| `io_assistant/updates/apply.py` (create) | `UpdateChecker` thread + `spawn_update` |
| `io_assistant/service/app.py` (modify) | `GET /update`, `POST /update/apply`, start checker |
| `io_assistant/cli.py` (modify) | `io update --check / --localize` |
| `scripts/update.ps1` (create) | detached apply script |
| `frontend/api.js`, `components/settings.js`, `app.js`, `index.html`, `app.css` (modify) | pill + Settings → Updates |
| `.gitignore`, `.claude/rules/local-first.md`, knowledge doc (modify) | ignore `config.local.toml`; document |

---

### Task 1: `[updates]` config + layered `config.local.toml`

**Files:** Modify `io_assistant/config.py`, `.gitignore`; Test `tests/test_config.py` (append)

**Interfaces — Produces:** `UpdatesConfig(enabled: bool=True, remote: str="origin", branch: str="", interval_h: float=6.0, repo_dir: str="")`; `Config.updates: UpdatesConfig`; `deep_merge(base: dict, over: dict) -> dict`; `load_config` merges `<config.toml dir>/config.local.toml` (if present) over the base.

- [ ] Tests: (a) `config.local.toml` overriding `[backend] provider` and adding `[updates] interval_h` yields the merged values while untouched keys keep the base values; (b) missing local file is fine; (c) invalid TOML in the local file raises `ConfigError` naming that file; (d) `cfg.updates.enabled` defaults to True.
- [ ] Run → FAIL. Implement `UpdatesConfig`, `deep_merge` (recursive for dicts, override wins otherwise), local-file merge in `load_config` before env overrides. Add `/config.local.toml` to `.gitignore`.
- [ ] Run → PASS. Commit `feat(config): [updates] section + layered config.local.toml`.

### Task 2: `check()` against real git repos

**Files:** Create `io_assistant/updates/__init__.py`, `io_assistant/updates/check.py`; Test `tests/test_updates_check.py`

**Interfaces — Produces:**
`@dataclass UpdateStatus(available: bool=False, behind: int=0, subjects: list[str]=[], dirty: bool=False, branch: str="", sha: str="", error: str|None=None, checked_at: float|None=None)` with `as_dict()`;
`find_repo(config) -> Path | None` (first of `updates.repo_dir`, source root `parents[2]`, `Path.cwd()` that contains `.git`);
`check(repo: Path, remote: str="origin", branch: str="", timeout: float=15.0) -> UpdateStatus` — never raises; failures land in `.error`.

- [ ] Tests (helper builds a bare `remote.git`, a `work` clone, pushes an initial commit): (1) up to date → `available False, behind 0`; (2) push 2 commits from a second clone → `available True, behind 2`, `subjects` newest-first; (3) modify a tracked file locally → `dirty True`; (4) untracked file only → `dirty False`; (5) remote path deleted → `error` set, `available False`, no exception; (6) `branch=""` on a local-only branch (no `origin/<branch>`) → `available False`; (7) explicit `branch="main"` while on another local branch compares against `origin/main`.
- [ ] Run → FAIL. Implement with `subprocess.run([...], capture_output=True, text=True, timeout=..., env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})`: `git fetch <remote> [<branch>]`, `git rev-parse --abbrev-ref HEAD`, `git rev-parse --short HEAD`, `git rev-list --count HEAD..<remote>/<branch>`, `git log --format=%s -n 20 HEAD..<remote>/<branch>`, `git status --porcelain --untracked-files=no`.
- [ ] Run → PASS. Commit `feat(updates): git-based update check`.

### Task 3: one-time config localisation + `io update` CLI

**Files:** Create `io_assistant/updates/localize.py`; Modify `io_assistant/cli.py`; Test `tests/test_updates_localize.py`

**Interfaces — Produces:** `split_local(repo: Path) -> dict` — diff of the working `config.toml` vs `git show HEAD:config.toml` (nested dict of only changed/added keys); if non-empty and `config.local.toml` does not exist: writes it (`dump_toml`), then `git checkout -- config.toml`; returns the diff. `dump_toml(d: dict) -> str` for str/int/float/bool/list-of-scalars in nested tables. CLI: `io update --check` prints status; `io update --localize` calls `split_local(find_repo(...))`.

- [ ] Tests (real temp repo with a committed `config.toml`): (1) edited working file → local holds only the edited keys, `config.toml` restored to HEAD, and `load_config` of the pair equals the original edited values; (2) unchanged file → no local file written; (3) existing `config.local.toml` is never overwritten; (4) `dump_toml` round-trips through `tomllib` for str with quotes, bools, ints, floats, lists.
- [ ] Run → FAIL. Implement. Run → PASS. Commit `feat(updates): move user config edits into config.local.toml`.

### Task 4: service — checker thread, endpoints, `update.ps1`

**Files:** Create `io_assistant/updates/apply.py`, `scripts/update.ps1`; Modify `io_assistant/service/app.py`; Test `tests/test_service_update.py`

**Interfaces — Consumes:** Task 2 `check`/`find_repo`/`UpdateStatus`. **Produces:** `UpdateChecker(config, *, repo=None)` with `.status -> UpdateStatus`, `.check_now() -> UpdateStatus`, `.start()`, `.stop()` (interval `updates.interval_h`, first check after 15 s, never raises); `spawn_update(repo: Path, relaunch: str) -> None` (detached `powershell -File scripts/update.ps1 -Root <repo> -ProcessId <pid> -Relaunch <exe|dev>`). Endpoints: `GET /update[?refresh=1]` → `UpdateStatus.as_dict()` plus `enabled`; `POST /update/apply` → 409 `detail` if not available / dirty / no repo, else `{"ok": true}` after calling `app.state.spawn_update` and scheduling `app.state.exit_fn` (default: `threading.Timer(1.0, os._exit, [0]).start()`).

- [ ] Tests (`create_app` with `object()` stubs like `test_frontend_assets`, then set `app.state.updater` to a fake with a chosen status and patch `app.state.spawn_update` / `app.state.exit_fn`): (1) `GET /update` with `[updates] enabled=false` → `{"enabled": false, "available": false}`; (2) `GET /update` returns the fake's status; `?refresh=1` calls `check_now`; (3) `POST /update/apply` with `available=False` → 409 and spawn not called; (4) with `dirty=True` → 409; (5) with `available=True` → 200, spawn called once with the repo and `exit_fn` called once.
- [ ] Run → FAIL. Implement checker + endpoints (checker created always; thread started only when `engine is None`). `update.ps1` steps: wait for `-ProcessId` to exit (≤30 s); `docker compose -p io exec -T db pg_dump -U io io` into `~/.local/share/io/backups/pre-update-<sha>.sql`, prune to 3; if no `config.local.toml`, run `uv run io update --localize`; require a clean tracked tree else abort; `git pull --ff-only`; `uv sync`; if `dist\IO\IO.exe` exists run `dev.ps1 build`; on any failure `git reset --hard <old sha>`; always relaunch (`-Relaunch exe` → start `dist\IO\IO.exe`, `dev` → `dev.ps1 up`) and append a result line to `~/.local/share/io/update.log`. Verify `update.ps1` parses (PowerShell AST, zero errors) and dry-run against a scratch clone by hand.
- [ ] Run → PASS. Commit `feat(updates): update endpoints, checker thread, update.ps1`.

### Task 5: UI — topbar pill and Settings → Updates

**Files:** Modify `frontend/api.js`, `frontend/components/settings.js`, `frontend/app.js`, `frontend/index.html`, `frontend/app.css`; docs `.claude/rules/local-first.md`, `.claude/knowledge/desktop-app.md`, `.claude/state/*`

**Interfaces — Consumes:** Task 4 endpoints. **Produces:** `api.update(refresh=false)`, `api.applyUpdate()`; `<button id="update-pill" hidden>`; a Settings "Updates" section.

- [ ] Add API methods; in `app.js` fetch `api.update()` after health and every 30 min, show `#update-pill` ("Update available · N") when `available`, click opens Settings. Settings → Updates: branch + short SHA, last checked, commit subjects (escaped), **Check now** (`refresh=1`), **Update & restart** (confirm, disabled while dirty with the reason), error text.
- [ ] Verify in the browser pane with a static server and a stubbed `api.update` (available, dirty, error, none states); `node --check` all JS; frontend tests green. Add `local-first.md` case 7 (git fetch). Commit `feat(ui): update pill and Settings → Updates`.

---

## Self-review

Spec coverage: check (T2), config layering + migration (T1, T3), apply + snapshot + rollback (T4), UI (T5), rules (T5), tests on real repos (T2, T3). Spec deviations: `branch=""` default (noted above). Type names used consistently: `UpdateStatus`, `UpdateChecker`, `find_repo`, `check`, `split_local`, `dump_toml`, `spawn_update`, `deep_merge`.
