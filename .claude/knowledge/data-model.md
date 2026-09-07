# Data model (PostgreSQL 16 + pgvector)

**Verbatim log:** `utterances` — `id`, `text` (raw, never mutated), `source`
(`voice` | `text`), `captured_at timestamptz`, `transcription_confidence float
null`, `resolved_intent` (`store` | `query` | `unknown`).

**Entity tables** — `people` (`canonical_name`, `aliases text[]`, `notes`),
`places` (`name`, `type`, `aliases`), `items` (`name`, `category`, `aliases`),
`occasions` (`name`, `date`, `recurrence_rule text null`). Each has an
`embedding vector` column and `created_at` / `updated_at`.

**The open-ended `records` table** — the single table for everything that
happened, is to be done, or is a note about the user's life. Columns: `id`,
`kind text` (a lowercase snake_case slug the model coins — `event`, `task`,
`chore` are well-known and special-cased; anything else like `gym_session`,
`health_note`, `expense` is free-form and fine), `domain text null` (coarse
bucket from a small open set: `social` `job` `home` `health` `finance`
`learning` `errand` `other`), `title text`, `body text null`,
`occurred_at timestamptz null`, `due_at timestamptz null`, `status text null`
(`open` | `done` | `dropped`, or null for pure events/notes),
`recurrence_rule text null` (iCal RRULE), `assigned_by_person_id fk null`,
`attributes jsonb` (any other structured detail), `source_utterance_id fk`,
`embedding vector`, `created_at`, `updated_at`.
**New life domains ("job", "gym", "health") become new `kind` / `domain` string
values, NEVER a new table.**

**Link tables** — `record_people`, `record_places`, `record_items`,
`record_occasions`, `occasion_people`. Each is `(record_id|occasion_id,
entity_id, role text null)`.

**Indexing** — HNSW index on every `embedding` column (people, places, items,
occasions, records); b-tree on every foreign key and every timestamp
(`records.occurred_at`, `records.due_at`, `utterances.captured_at`,
`occasions.date`) plus b-tree on `records.kind` and `records.domain`; GIN on the
`aliases` arrays.

**Migrations** — Alembic only, from the first commit. No ad-hoc `ALTER`. The
embedding dimension is fixed in config; changing it or the embedding model is a
migration plus a full backfill.
