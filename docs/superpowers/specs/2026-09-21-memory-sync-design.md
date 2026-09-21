# Accounts and memory sync (Supabase)

Date: 2026-09-21 · Status: approved design, awaiting spec review

## Goal

Tell IO about a friend, a task or an affiliation on one device and have it on
every signed-in device, with no desktop required (the phone app, a separate
sub-project, is a standalone client of the same protocol). Opt-in: signed out,
IO is fully local exactly as today.

## Decisions (from brainstorming)

- Hosted **Supabase** (Postgres + Auth + row-level security).
- **Server-readable**: encrypted in transit (TLS) and at rest only, not
  end-to-end. Chosen over E2EE for simplicity and server-side flexibility.
  This is a deliberate move away from "your data stays on your machine";
  `local-first.md` is amended plainly.
- Sync scope: people, places, items, occasions, records (incl. tasks and
  collections), affiliations (join tables), conversations, messages,
  utterances. **Not synced:** files/file index (device-local paths), web cache,
  embeddings (each device re-embeds received text via the backfill in
  `2026-09-21-ollama-optional-design.md`).

## Design

1. **Server schema.** Mirror tables with `user_id` (RLS: a user sees only their
   rows), global `sync_id uuid` primary key, `rev bigint` from a sequence via
   trigger (ordering never depends on device clocks), `deleted`/`merged_into`
   tombstone columns.
2. **Local migration (Alembic).** Add `sync_id uuid` (default generated) to the
   synced tables; add `updated_at` to the join tables and `messages`; add
   `sync_tombstones(table, sync_id, merged_into)` written by delete paths (no
   read-path change) and `sync_state(device_id, last_pulled_rev,
   last_pushed_at)`. Local integer PKs stay; the wire uses `sync_id`.
3. **Sync loop** — `io_assistant/sync/`, a daemon thread modelled on
   `TrackerPoller`: push rows changed since `last_pushed_at` (upsert by
   `sync_id`) plus tombstones; pull rows with `rev > last_pulled_rev`. Runs on
   an interval while the app is open and right after a turn that wrote.
   Realtime channels are a later optimisation.
4. **Merge (deterministic Python; the model never decides identity).**
   - Rows: last-writer-wins by `rev`; a task's `completed_at` is sticky (a stale
     edit cannot reopen a finished task).
   - Incoming people/places/items/occasions run through the existing
     `EntityResolver`. A confident match collapses the two `sync_id`s: the
     earlier-created row wins, the other is tombstoned with `merged_into`, join
     rows are repointed, aliases unioned.
   - Applying a pulled row never re-triggers a push of the same revision.
5. **Auth.** Supabase Auth (email; Google/Apple later). The session token is
   kept in the OS keychain; the password is never stored. `[sync] enabled =
   false` default, plus `url` / `anon_key` (public, safe in config).
6. **UI.** Settings → Account (sign in/out, status, Sync now, last synced);
   a sync indicator beside `#status`.
7. **Rules.** `local-first.md`: one sanctioned host, the configured Supabase
   project, only when signed in and `[sync].enabled`, carrying synced tables in
   plaintext over TLS.

## Testing

A second real Postgres database stands in for the server, with the same schema
and `rev` trigger, so push, pull, merge, tombstones and the duplicate-entity
collapse run end to end with no mocks. Two local databases play two devices.
The phone client implements the same protocol from this spec and is checked
against shared conformance fixtures (JSON change sets and expected merged
state).

## Out of scope / later

End-to-end encryption; syncing files or the file index; realtime push; a
per-field merge; OpenAI or other providers. Every new synced table needs a
`sync_id` migration: add that to the "new entity type" skill checklist.

## Risks

- Duplicate-entity merges are irreversible for the tombstoned `sync_id`; the
  resolver's confidence threshold must be conservative for merges (a merge
  needs `>=` the resolver's existing confident-match bar, not the fuzzy one).
- Users signed in on two devices with divergent pre-sync data get a one-time
  large first merge; run it in batches with progress.
