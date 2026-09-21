# Memory Sync (Google Drive) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (or subagent-driven-development). Steps use checkbox syntax.

**Goal:** Memories, affiliations, tasks and chats written on one device appear on every signed-in device, through the user's own Google Drive, at $0.

**Architecture:** A store-agnostic `SyncEngine` pushes rows changed since their last push as per-device batch files and pulls other devices' files, merging with deterministic Python (last-writer-wins, sticky task completion, resolver-based duplicate collapse). Transport is a `SyncStore` interface with a `FolderStore` (tests, any synced folder) and a `GoogleDriveStore` (Drive `appDataFolder`).

**Tech Stack:** Python 3.11, SQLAlchemy + Alembic + Postgres, `google-api-python-client`, `google-auth-oauthlib`, `keyring`, pytest against two real databases.

**Spec:** `docs/superpowers/specs/2026-09-21-memory-sync-design.md`

## Global Constraints

- Tests use real PostgreSQL (two databases for two devices); never mock the DB. The transport in tests is a real `FolderStore` on a tmp dir.
- Schema changes are Alembic migrations only (`0010`). No embedding column is synced; the embedding backfill refills vectors on receipt.
- The model (LLM) never decides identity or merges: all merge logic is deterministic Python (llm-boundaries rule).
- Local-first: sync is opt-in (`[sync] enabled = false` by default) and adds only Google endpoints when enabled and signed in (rule case 8).
- Everything through `uv run`. Test command: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run pytest -q -p no:warnings`.
- No background threads in tests' `create_app` (same guard as the backfiller/checker: only when `create_app` owns its engine).

## File structure

| File | Responsibility |
|---|---|
| `io_assistant/db/migrations/versions/0010_sync.py`, `db/models.py` (modify/create) | `sync_id`, `synced_at`, missing `updated_at`; `sync_tombstones`, `sync_aliases`, `sync_state` |
| `io_assistant/db/sync_hooks.py` (create) | `before_flush` tombstone recorder |
| `io_assistant/sync/codec.py` (create) | table registry, row ⇄ dict, dependency order |
| `io_assistant/sync/store.py`, `stores.py` (create) | `SyncStore` protocol, `FolderStore` |
| `io_assistant/sync/engine.py` (create) | `SyncEngine.push / pull / snapshot / sync` and merge |
| `io_assistant/sync/gdrive.py`, `auth.py` (create) | `GoogleDriveStore`, OAuth + keychain |
| `io_assistant/sync/poller.py` (create) | `SyncPoller` thread |
| `io_assistant/config.py`, `service/app.py`, `cli.py` (modify) | `[sync]`, endpoints, wiring |
| `frontend/…` (modify) | Settings → Account |

---

### Task 1: schema — `sync_id`, `synced_at`, tombstones, aliases, state

**Files:** Create `0010_sync.py`, `io_assistant/db/sync_hooks.py`; Modify `db/models.py`; Test `tests/test_sync_schema.py`

**Interfaces — Produces:** on `Person, Place, Item, Occasion, Record, Collection, Conversation, Message, Utterance`: `sync_id: uuid` (unique, default `gen_random_uuid()`), `synced_at: timestamptz|null`; `updated_at` added (default `now()`) to `Utterance, Conversation, Message`; on the five link tables `synced_at`. New models `SyncTombstone(id, table_name, sync_id, merged_into, deleted_at)`, `SyncAlias(alias uuid pk, canonical uuid)`, `SyncState(key text pk, value jsonb)`. `sync_hooks.install()` registers a `before_flush` that inserts a `SyncTombstone` for every deleted synced-model row unless `session.info.get("sync_applying")`.

- [ ] Tests: new rows get distinct `sync_id`s and `synced_at IS NULL`; deleting a `Record`/`Person` via `session.delete` writes exactly one tombstone with the right table and `sync_id`; with `session.info["sync_applying"]=True` no tombstone is written; deleting a record cascades its link rows without extra tombstones; `updated_at` moves on update for `Message`.
- [ ] Implement migration + models + hook (installed at the bottom of `models.py`). Run → PASS. Commit.

### Task 2: codec

**Files:** Create `io_assistant/sync/__init__.py`, `codec.py`; Test `tests/test_sync_codec.py`

**Interfaces — Produces:** `TABLES` (ordered: utterances, people, places, items, occasions, conversations, collections, records, messages) and `LINKS` (the five link tables with their two parent tables); `encode_row(session, obj) -> dict` (`{"t": table, "sync_id": str, "updated_at": iso, "data": {...}}` with FK columns replaced by parent `sync_id` strings, `embedding` and `id` omitted); `decode_row(session, table, data, aliases) -> dict` of column kwargs with FK sync_ids resolved to local ids (raises `Unresolved(table, sync_id)`); `encode_link(session, obj)`, link identity `"<parent_sync>:<parent_sync>"`.

- [ ] Tests (real DB): round-trip a record with people/place links into dicts and back into a second session's ids; FK of a deleted parent raises `Unresolved`; aliases map a loser `sync_id` to its winner; embeddings never appear in the payload; JSONB, arrays, dates, datetimes serialise to JSON-safe values and back.
- [ ] Implement. Run → PASS. Commit.

### Task 3: transport + push

**Files:** Create `io_assistant/sync/store.py`, `stores.py`, `engine.py` (push part); Test `tests/test_sync_push.py`

**Interfaces — Produces:** `SyncStore` protocol; `FolderStore(root: Path)`; `SyncEngine(session_factory, store, device_id, *, clock=time.time)`; `.push() -> int` writes one `dev-<id>/batch-<seq>.json.gz` containing dirty rows (in `TABLES` order, then links) plus new tombstones, sets `synced_at := updated_at` per pushed row, increments `seq` in `sync_state`; returns rows pushed (0 writes no file).

- [ ] Tests: after a local write, `push()` returns N and one batch file exists; a second `push()` pushes 0 and writes nothing; editing one row pushes only that row; a delete pushes a tombstone once; a row edited *during* push (simulated by editing after the read) is dirty again.
- [ ] Implement. Run → PASS. Commit.

### Task 4: pull, merge, snapshot (the core)

**Files:** Modify `engine.py`; Test `tests/test_sync_merge.py` (uses two real databases via a `devices` fixture in `tests/conftest.py`: create `io_sync_a`/`io_sync_b`(/`c`) if missing, run migrations, truncate between tests, drop nothing)

**Interfaces — Produces:** `.pull() -> int` (rows applied), `.snapshot()`, `.sync() -> (pushed, pulled)`; merge rules from the spec.

- [ ] Tests (each with A and B as engines over one shared tmp `FolderStore`): (1) a record + person + link written on A appears on B with affiliations intact; (2) B's edit wins over A's older edit, and A over B's when newer; equal timestamps break on device id deterministically; (3) delete on A removes it on B via tombstone; (4) a task completed on A and edited (older) on B stays done; (5) A and B independently create "Nafay": after syncing both, each has exactly one Nafay with the same `sync_id`, aliases unioned, records referencing either point to it; (6) vector-only near-duplicates are *not* merged; (7) no echo: after a full round `push()` on both returns 0; (8) after ≥50 batches `snapshot()` compacts and a fresh device C bootstraps to the same state; (9) an unresolved foreign key leaves `last_applied` unchanged and the next `pull()` succeeds once the parent arrives; (10) future timestamps are clamped.
- [ ] Implement pull/apply (per file, dependency order, `session.info["sync_applying"]=True`), LWW, sticky completion, resolver-based collapse + `sync_aliases`, snapshot + compaction. Run → PASS. Commit.

### Task 5: Google Drive store, OAuth, service, config

**Files:** Create `io_assistant/sync/gdrive.py`, `auth.py`, `poller.py`; Modify `config.py`, `service/app.py`, `cli.py`, `pyproject.toml` (deps), `.claude/rules/local-first.md`; Test `tests/test_sync_service.py`, `tests/test_sync_gdrive.py`

**Interfaces — Produces:** `SyncConfig(enabled=False, folder="", client_id="", client_secret="", interval_s=60)`; `GoogleDriveStore(credentials)` implementing `SyncStore` over Drive `appDataFolder` (paths → file names `dev-<id>__batch-<seq>` since Drive has no folders in appData; `list(prefix)` via `files.list` with `spaces=appDataFolder` and name-prefix query); `auth.sign_in(client_id, client_secret) -> Credentials` (loopback flow, opens the browser), `auth.load()/save()/clear()` via `keyring`; `SyncPoller(engine, interval_s)`; endpoints `GET /sync` → `{enabled, signed_in, syncing, last_synced_at, error, device_id}`, `POST /sync/now`, `POST /sync/signin`, `POST /sync/signout`.

- [ ] Tests: `GET /sync` disabled/enabled shapes with a fake engine; `POST /sync/now` runs `engine.sync()` and reports counts/error; signin/out call injected auth hooks; `GoogleDriveStore`'s name mapping and query building are unit-tested with a fake Drive client; real-Drive test is opt-in (`IO_GDRIVE_TESTS=1` + credentials).
- [ ] Implement; add deps via `uv add google-api-python-client google-auth-oauthlib keyring`; poller starts only when `create_app` owns its engine and `sync.enabled` and signed in (or `folder` set). Add local-first case 8. Run → PASS. Commit.

### Task 6: UI — Settings → Account

**Files:** Modify `frontend/api.js`, `components/settings.js`, `app.js`, `app.css`; docs and state files

- [ ] `api.sync()`, `syncNow()`, `syncSignIn()`, `syncSignOut()`; Settings → Account section (status, last synced, error, Sign in with Google / Sign out / Sync now); a sync dot beside `#status`. Pure wording helper `syncMessage(s)` in `frontend/sync.js` with a node test first. Verify in the browser pane with stubbed API states. Write the Google Cloud setup steps into `.claude/knowledge/memory-sync.md`. Commit.

---

## Self-review

Spec coverage: transport + layout (T3/T4/T5), pull cadence (T5), codec/FK mapping (T2), dirty tracking + tombstones (T1/T3), merge rules (T4), auth + config + rules (T5), UI (T6), tests on two real DBs (T4). Names used consistently: `SyncStore`, `FolderStore`, `SyncEngine`, `sync_id`, `synced_at`, `SyncTombstone`, `SyncAlias`, `SyncState`, `Unresolved`.
