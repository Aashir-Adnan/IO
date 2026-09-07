# Extraction & storage pipeline

Runs when Route returns `STORE`.

**Extract** — prompt is a system schema description + few-shot examples + the
utterance. Output is JSON only: arrays of `people`, `places`, `items`,
`occasions`, and one or more `records`. Each record carries `kind` (model picks
a slug — `event` / `task` / `chore` for well-known cases, else a
domain-appropriate slug), optional `domain`, `title`, and only the other fields
the model can fill (`body`, `when_phrase`, `due_phrase`, `recurrence_phrase`,
`status`, `assigned_by`, nested `people`/`places`/`items`/`occasions`,
`attributes`), plus a `confidence` float in `[0,1]`. Deterministic code then
normalizes `kind`/`domain` (lowercase, snake_case, domain clamped to the known
set, unknown → `other`). Validation is via Pydantic; on failure, one retry with
a "return valid JSON" nudge, then route becomes `UNKNOWN` with an
`extraction_failed` marker.

**Resolve entities** — for each person/place/item, in order: (1) exact match on
canonical name or alias (case-insensitive) → use it; (2) fuzzy match
(`rapidfuzz` token-set ratio) above the high threshold (default 92) → use it;
(3) vector similarity above the threshold (default 0.85) → ambiguous, hold for
the gate; (4) no match → stage a new entity.

**Ownership split** — `io_assistant.resolve.resolver.EntityResolver` owns
person/place/item creation *and* computing/storing their `embedding`
(`EntityResolver.create`). `persist.writer` owns `records` rows, `occasions`
rows, and all link rows (plus their embeddings).

**Confirmation gate** — triggered only by: an ambiguous vector-only resolve, or
a record with `confidence` below the gate threshold (default 0.6), or a
date/time the grounder could not resolve. When triggered, the assistant emits a
one-line summary and waits for `yes` / `no` / a correction. Otherwise it stores
silently then prints what it wrote.

**Ground dates** — deterministic app code resolves relative time expressions
("last Tuesday", "this morning", "for his birthday") against `now()` and, for
occasion references, against stored `occasions` rows. The model never computes
dates.

**Persist** — one transaction: insert/update entities, insert the record(s) with
grounded `occurred_at` / `due_at` / `recurrence_rule` / `assigned_by_person_id`,
insert link rows, compute and store embeddings for every new/updated text row
(record embedding = `title` + `body`), stamp `source_utterance_id` and set
`utterances.resolved_intent = 'store'`. Recurring items ("trash out every
Monday") are a `chore` record with `recurrence_rule` set and `due_at` null,
never expanded at store time.
