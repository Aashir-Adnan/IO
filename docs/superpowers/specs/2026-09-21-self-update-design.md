# Self-update from GitHub

Date: 2026-09-21 · Status: approved design, awaiting spec review

## Goal

IO checks its GitHub repo for new commits, offers the update, then pulls,
rebuilds and relaunches while keeping all user data and settings. Delivery
model: **the git checkout is the install** (no CI-built releases).

## What must survive an update

Postgres data (Docker volume `io_pgdata`), `.env`, `~/.local/share/io/*`
(window geometry, models, thumbnails), and the user's `config.toml` edits.
Migrations already run on every launch (`ensure_database` →
`alembic upgrade head`), so schema changes apply themselves.

## Design

1. **Check** — `io_assistant/updates/check.py`: `git fetch origin <branch>`
   (15 s timeout) in the install root; compare `HEAD` with `origin/<branch>`.
   Returns `{available, behind, subjects[], dirty, branch, sha}`. Plain git only:
   no GitHub API, no token stored by IO; private repos work via the user's git
   credentials. Runs at startup and every `interval_h` in a daemon thread.
   `GET /update` reports it; `POST /update/apply` starts an update.
   Config: `[updates] enabled = true, remote = "origin", branch = "main",
   interval_h = 6`. Never auto-applied.
2. **Config layering.** `load_config` deep-merges a gitignored
   `config.local.toml` (next to `config.toml`) over the tracked `config.toml`.
   The updater's first run migrates existing edits: diff the working
   `config.toml` against `HEAD:config.toml`, write only the differences to
   `config.local.toml`, restore the tracked file.
3. **Apply** — `POST /update/apply` spawns a detached `scripts/update.ps1` and
   exits IO (a running process cannot replace its own venv/exe). The script:
   1. wait for IO to exit;
   2. `pg_dump` to `~/.local/share/io/backups/pre-update-<sha>.sql`, keep the
      last 3;
   3. require a clean tracked tree; `git pull --ff-only` (abort with a message
      if dirty/diverged);
   4. `uv sync`;
   5. `dev.ps1 build` only if `dist/IO/IO.exe` exists;
   6. relaunch (`dev.ps1 up` or the exe).
   Failure at 3-5: `git reset --hard <old sha>` (safe: tree was verified clean,
   no migration has run) and report. Failure after launch/migration: leave the
   code as pulled and point to the snapshot.
4. **UI** — topbar pill "Update available · N changes"; Settings → Updates
   (branch, short SHA, last checked, commit subjects, Check now, Update &
   restart).
5. **Rules** — `local-first.md` gains a sanctioned case: `git fetch` to the
   configured remote only, only when `[updates].enabled`; git protocol only, no
   IO identifiers.

## Testing

`check()` and config layering are tested against real temporary git repos (a
bare remote plus a clone, commits added to the remote) and the real Postgres
test DB; no mocks. `update.ps1` is verified by hand against a scratch clone
(a script that swaps its own environment isn't reasonably unit-testable).

## Out of scope

CI-built releases and signed installers; auto-apply; rollback of a migrated
database beyond the pre-update snapshot.
