# Memory sync via Google Drive

Date: 2026-09-21 (revised 2026-09-22: Drive instead of Supabase) · Status: approved

## Goal

Tell IO about a friend, a task or an affiliation on one device and have it on
every signed-in device, with no desktop required (the phone app is a separate
sub-project and a standalone client of the same protocol). Opt-in: signed out,
IO is fully local exactly as today. Cost: $0.

## Decisions (from brainstorming)

- **Google Drive `appDataFolder`** (scope `drive.appdata`, non-sensitive) as the
  transport, not a hosted database: nothing to run, nothing to pay for, no
  project that pauses, and the data lives in the user's own Google account with
  no IO operator in between. The Google account *is* the account.
- Earlier choices (Supabase, server-readable) are superseded. Encryption of
  the synced files is possible later (no server has to read them) but is out of
  this pass.
- Sync scope: people, places, items, occasions, records (incl. tasks and
  collections), affiliations (join tables), conversations, messages,
  utterances. **Not synced:** files/file index, web cache, embeddings (each
  device re-embeds received text via the backfill in
  `2026-09-21-ollama-optional-design.md`).

## Design

1. **Transport interface** — `SyncStore`: `put(path, bytes)`, `get(path)`,
   `list(prefix)`, `delete(path)`. Two implementations: `FolderStore` (a plain
   directory — used by the tests, and it also lets a OneDrive/Dropbox folder
   work) and `GoogleDriveStore` (Drive `appDataFolder`, `files.list` / `create`
   / `get` / `delete`).
2. **Layout** — each device writes only its own files, so writes never
   conflict: `dev-<device_id>/batch-<seq:08d>.json.gz` (rows changed since its
   last push) and `dev-<device_id>/snapshot-<seq:08d>.json.gz` (every live row +
   tombstones as of that seq). After 50 batches a device writes a snapshot and
   deletes its older batches, which bounds the file count and bootstraps a new
   device.
3. **Pull** — list `dev-*/`, and for each other device apply its newest snapshot
   if it is ahead of `last_applied[device]`, then its batches in order. A poller
   thread does this every 60 s while the app is open, and right after a local
   write. No push channel. Rows are applied per file in dependency order;
   a row whose foreign key can't be resolved aborts the cycle without advancing
   (retried next cycle).
4. **Row format** — a generic codec over the SQLAlchemy models: every column
   except `id` and `embedding`; foreign keys are carried as the target row's
   `sync_id`; affiliations (join tables) are identified by the pair of parent
   `sync_id`s. Rows carry `updated_at`; deletions and merges are tombstones.
5. **Dirty tracking** — each synced table gets `sync_id uuid` and `synced_at`
   (join tables: `synced_at` only; tables lacking `updated_at` gain it). A row
   is dirty when `synced_at IS NULL OR updated_at > synced_at`. After a push,
   `synced_at := updated_at` (as read), and a pulled row is written with both
   set equal, so there is no echo. Deletes are recorded by a `before_flush`
   hook into `sync_tombstones(table, sync_id, merged_into)`; the hook is
   suppressed while applying remote changes.
6. **Merge (deterministic Python; the model never decides identity)**
   - Rows: last-writer-wins by `(updated_at, device_id)`. Timestamps more than
     a few minutes in the future are clamped. Known limit: badly skewed device
     clocks can flip an edit.
   - A task's `completed_at`/`status = done` is sticky: a stale edit cannot
     reopen a finished task.
   - A new incoming person/place/item is run through the existing
     `EntityResolver`; a confident match (exact or fuzzy; not the
     vector-only "ambiguous" outcome) collapses the two `sync_id`s. The
     earlier-`created_at` row wins (tie: lowest `sync_id`), the other becomes a
     tombstone with `merged_into` and an entry in `sync_aliases`, so any row
     referencing the loser resolves to the winner. Both devices reach the same
     result independently. Occasions are not collapsed (the resolver doesn't
     cover them).
7. **Auth** — Google OAuth: a loopback flow on desktop
   (`google-auth-oauthlib`), Google Sign-In on the phone; scope `drive.appdata`
   only, so IO can never see the rest of the Drive. The refresh token lives in
   the OS keychain (`keyring`); the password is never seen. The user creates a
   free Google Cloud project and OAuth client once, and sets the consent screen
   to "In production" (in "Testing" refresh tokens expire after 7 days;
   they also expire after 6 months unused). `[sync] enabled = false` by
   default, plus `client_id`, `client_secret` (a desktop-app secret is not
   confidential), `folder` (for `FolderStore` instead of Drive).
8. **UI** — Settings → Account (sign in/out, status, Sync now, last synced,
   error text); a sync indicator beside `#status`.
9. **Rules** — `local-first.md` case 8: `accounts.google.com`, `oauth2.
   googleapis.com` and `www.googleapis.com`, only when `[sync].enabled` and
   signed in, carrying synced tables in plaintext (Google encrypts at rest)
   into the user's own Drive.

## Testing

Two real Postgres databases stand in for two devices, syncing through a real
`FolderStore` directory: push/pull, LWW, sticky completion, tombstones,
duplicate-entity collapse convergence, snapshot bootstrap of a third device, no
echo. No mocks. `GoogleDriveStore` has opt-in tests (needs credentials) and a
unit test of its query/naming logic. The phone client implements the same
protocol against shared conformance fixtures (JSON batches + expected state).

## Out of scope / later

Encryption; realtime push (Drive push needs a webhook); syncing files; a
per-field merge; the phone client itself. Every new synced table needs a
`sync_id` migration and an entry in the codec registry (add to the "new entity
type" skill checklist).

## Risks

- Duplicate-entity merges are irreversible for the tombstoned `sync_id`; only
  exact/fuzzy resolver matches merge.
- Wall-clock LWW (see above).
- Drive is eventually consistent: a freshly written file may be listed a
  moment late; the next poll picks it up.
- First sync between two devices with divergent pre-existing data is one large
  merge; it runs in file-sized batches.
