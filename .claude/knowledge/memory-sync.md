# Memory sync (Google Drive)

Spec `docs/superpowers/specs/2026-09-21-memory-sync-design.md`, plan
`docs/superpowers/plans/2026-09-22-memory-sync.md`. Opt-in (`[sync] enabled`);
signed out, IO is fully local.

## How it works

`io_assistant/sync/`:
- `codec.py` — table registry (`TABLES`, `LINKS`), `IdMap`, row/link ⇄ dict. Foreign
  keys travel as the parent's `sync_id`; embeddings are never synced.
- `engine.py` — `SyncEngine.push/pull/snapshot/sync`. Each device writes only its own
  files (`dev-<id>/batch-<seq>` and `snapshot-<seq>`), so writes never conflict.
  Merge: last-writer-wins on `updated_at` (future timestamps clamped to +5 min; an
  exact tie is a no-op), `done` tasks stay done, deletes are tombstones (a tombstoned
  row is never resurrected), and an incoming person/place/item that exactly or
  fuzzily matches an existing one collapses into it (earlier `created_at` keeps its
  `sync_id`; the other becomes an alias + tombstone). Vector-only look-alikes and
  occasions are never merged.
- `stores.py` `FolderStore` (a directory — tests, or any OneDrive/Dropbox folder) and
  `gdrive.py` `GoogleDriveStore` (Drive `appDataFolder`; `dev-A/x` is stored as
  `dev-A__x`).
- `manager.py` `SyncManager` — store choice, sign-in thread, 60 s loop, `poke()` after
  a turn, `status()`. Service: `GET /sync`, `POST /sync/now|signin|signout`.
- Dirty tracking (migration 0010): `sync_id` + `synced_at` per synced table; dirty =
  `synced_at IS NULL OR updated_at > synced_at`. Deletes are recorded by the
  `before_flush` hook in `db/sync_hooks.py` (suppressed while applying remote changes).
  **A new synced table needs a `sync_id` migration and a `codec.TABLES` entry.**
- Gotcha for tests: never use a base timestamp later than the machine clock — the
  engine clamps future timestamps.

## One-time Google Cloud setup (free)

IO can't do this for you: it needs your own Google account.

1. console.cloud.google.com → create a project (e.g. "IO").
2. APIs & Services → Library → enable **Google Drive API**.
3. OAuth consent screen (Google Auth Platform): user type **External**, app name "IO",
   your email; add the scope `.../auth/drive.appdata`. **Set publishing status to "In
   production"** — in "Testing" refresh tokens expire after 7 days. (They also expire
   after 6 months unused.) `drive.appdata` is a non-sensitive scope.
4. Credentials → Create credentials → OAuth client ID → **Desktop app**. Copy the
   client ID and secret (an installed-app secret isn't confidential).
5. In `config.local.toml` (gitignored; never in `config.toml`):
   ```toml
   [sync]
   enabled = true
   client_id = "…apps.googleusercontent.com"
   client_secret = "…"
   ```
6. Restart IO → Settings → Account → **Sign in with Google**. Your own unverified app
   shows a warning: Advanced → "Go to IO (unsafe)". Repeat on each device.

No Google account handy, or want to try it first? Set `folder = "C:/Users/you/OneDrive/io-sync"`
instead: any synced directory works and needs no sign-in.

## Verifying against real Drive

`IO_GDRIVE_TESTS=1 uv run pytest tests/test_sync_gdrive.py -k real` (needs a prior
sign-in). The engine itself is tested with two/three real Postgres databases and a
real `FolderStore` (`tests/test_sync_merge.py`, fixture `devices`).
