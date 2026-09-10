# Tasks & Collections — design

Date: 2026-09-10
Branch base: `io-window-glass`
Status: approved, ready for implementation plan

## Problem

Two gaps in how IO handles the "things I need to do / keep a list of" side of a
user's life:

1. **Tasks never close.** "I need to X" is stored as a `task` with
   `status="open"` automatically, but nothing can mark it done:
   - Conversationally, "I finished the groceries" / "mark the milk done" is
     extracted as a *new* record with `status="done"` — a duplicate, not a
     close of the existing row. Matching an utterance to an existing record is
     entity-identity work, which is deterministic-Python territory and is
     unimplemented.
   - The `TaskListCard` renders checkboxes (`checkCircle` / `circle`) but they
     are not interactive.
   - The records browser (`views/records.js`) edits title and date only, never
     `status`.
   - Result: open tasks accumulate forever and keep appearing in "what do I
     need to do".

2. **Ad-hoc lists are unreliable to retrieve.** A novel `kind`
   ("movie_to_watch") stores fine — the `records` table is schema-less for
   `kind`/`domain`. But the query planner (`prompts/plan.txt`) is given only
   conversation history as context, never the set of kinds/collections the user
   actually has. It guesses `kind_filter` from wording. Coin "watchlist" once
   and "movies_to_watch" another time and the list silently fragments;
   "what films do I want to see" may match neither. There is no durable record
   of "the user keeps a watchlist; here is how it is keyed."

## Decisions (from brainstorming)

- A bare `task`/`chore` with **no date phrase** defaults to **due today** and
  **rolls forward** — it shows as due/overdue in "today" and "what do I need to
  do" queries until completed. No daily mutation job; the roll-forward is a
  read-time rule.
- A task can be completed by **either** a conversational phrase **or** a UI
  checkbox — both reach the same deterministic close path.
- Ad-hoc lists get a **learned collections registry**: the model proposes what
  a list is, deterministic Python owns its identity and storage, and the
  registry is fed back into routing so the list stays consistently findable.
- Delivered as **one spec, five phases**, each shippable and independently
  testable.

## LLM boundary (unchanged, load-bearing here)

The model is called only to **route / extract / plan / phrase / decide**. In
this feature specifically:

- The model may *identify* that a message is a completion ("I finished X") and
  produce a **search phrase** for the thing being closed. It never picks the
  record id and never writes `status`.
- The model may *propose* that a coined kind is a list, with a name, an item
  noun, and synonyms. Deterministic Python upserts the `collections` row,
  dedupes by slug, and decides identity.
- All matching (utterance → existing record, question → collection), date
  arithmetic (default-today, roll-forward), filtering, and ranking stay in
  Python (`resolve/`, `persist/`, `query/`).

---

## Phase 1 — Task completion

### 1.1 Kind normalization aliases

`io_assistant/models_domain.py::normalize_kind` currently only slugifies. Add a
small alias map applied after slugification:

```
todo, to_do, reminder, reminders  -> task
chores                            -> chore
```

`persist/writer.py::_STATUS_KINDS` stays `{"task", "chore"}`; the aliasing means
"remind me to…" reliably lands on `task` and gets `status="open"`.

Tests: `tests/test_models_domain.py` (new or existing) — alias cases.

### 1.2 `complete_record` — the deterministic close path

New module `io_assistant/tasks/complete.py`:

```
close_record(session, embedder, resolver_cfg, phrase, now, *, gate_threshold)
    -> CloseOutcome
```

- Build a `SubQuery(target_type="record", status_filter=["open"], semantic_hint=phrase)`
  restricted to status-bearing kinds (`task`, `chore`, and any kind registered
  in `collections` whose `field_hint` marks items as checkable — see Phase 3).
- Run it through the existing `retrieve_subquery` + `rank` path (structured +
  pgvector semantic), `now`-aware.
- `CloseOutcome`:
  - `matched` — exactly one confident row (top score ≥ threshold and clearly
    ahead of #2): flip `status="done"`, set `completed_at = now` (see 1.5),
    return the `Record`.
  - `ambiguous` — several plausible rows: return the top 2–3 as candidates for
    a gate.
  - `none` — nothing open matched: return empty; caller phrases "I don't see an
    open task like that."

No model call in this module.

### 1.3 Orchestrator wiring

Two entry points, mirroring the web feature:

- **Precheck** (backend-agnostic, primary): `_complete_precheck(text)` — a
  regex for completion shapes anchored on a leading verb:
  `^(mark|set|check off|tick off)\b .* \b(done|complete|completed|off)\b`,
  `^(i(?:'ve| have)?\s+)?(finished|completed|did|done with|wrapped up)\b`,
  `^(that'?s|it'?s)\s+(done|finished|handled)\b`.
  A first-person *future* need ("I need to", "I have to", "remind me") must NOT
  match — guard with the existing personal/negative lookarounds pattern style.
  On a hit, call `close_record` with the phrase = text minus the completion
  verb; return a `HandleResult` directly (no planner call).
- **Capability** (combined `decide` only): register `complete_record` in
  `io_assistant/actions/registry.py`:

  ```
  complete_record: "Mark an existing open task / list item as done — 'I finished
    the report', 'cross milk off the list', 'mark the dentist thing complete'.
    NOT for a new task the user still needs to do."
    args: { what: "string — the task or item being completed, as the user named it" }
  ```

  Handler `_action_complete_record` in the orchestrator calls the same
  `close_record`. Add to `decide.txt`'s step list implicitly via `{capabilities}`.

### 1.4 Confirmation gate for ambiguity

Reuse `PendingStore` / the gate mechanism. On `ambiguous`, return
`intent_kind="gate"` with a prose list ("Which one? 1. Call the dentist  2. Book
the dentist follow-up") and `pending` carrying the candidate ids + intended
`status`. A reply of "1" / "the first" / "the dentist one" is resolved
**in Python** (ordinal parse + fuzzy match against candidate titles) on the
next turn; no new model call. `dropped` ("cancel the dentist task",
"never mind the milk") uses the same path with `status="dropped"`.

### 1.5 Schema: `records.completed_at`

Migration `0008_task_completion` (branch head is currently `0007`):

- `records.completed_at TIMESTAMPTZ NULL` — set when `status` becomes `done`,
  cleared when it returns to `open`. Enables "what did I finish this week" and
  keeps a done task out of "today" while preserving history.

`persist/writer.py` and the `PATCH /record/{id}` handler both maintain it:
setting `status` to `done` with no `completed_at` → `completed_at = now`;
setting `status` back to `open` → `completed_at = NULL`.

`RecordEditIn` already accepts `status`. Add `status` handling symmetry for
`completed_at` in `service/app.py::record_edit`.

### 1.6 Frontend — checkbox is interactive

- `frontend/components/card.js` `tasklist` branch: wrap each row's glyph in a
  `<button class="task-check" data-id=... aria-pressed=...>`; click →
  `ctx.api.editRecord(id, { status: nextStatus })`, optimistic toggle of
  `.done` + glyph, revert on error. `renderCard` already receives `ctx`.
- `frontend/views/records.js`: add a leading check button to `rowEl` for
  `r.kind` in the status kinds (or `r.status` non-null); same `editRecord`
  call; strike-through `.record-title.done`.
- `frontend/app.css`: `.task-check` hit area, `.task-t.done` /
  `.record-title.done` strike + dim.
- No new endpoint — `PATCH /record/{id}` covers it.

### 1.7 `query_cards` widening

`orchestrator_cards.py::query_cards` currently emits a `TaskListCard` only when
`all(r.kind in ("task","chore") or r.due is not None)`. Widen to: emit it when
**any** returned row is a status-kind (`task`/`chore`/registered checkable
collection) and the answer shape is a list; non-task rows in the same answer
still render as their normal cards.

### Phase 1 tests

- `tests/test_tasks_complete.py` — `close_record` matched / ambiguous / none,
  against real Postgres with seeded open tasks + embeddings (FakeEmbedder ok
  for vectors, real SQL).
- `tests/test_orchestrator_tasks.py` — "I finished the groceries" closes the
  seeded row and does **not** create a new record; "I need to buy groceries"
  still stores a new open task (precheck must not false-positive); ambiguous →
  gate → "1" closes the right one.
- `tests/test_service_entity.py` — `PATCH /record {status:"done"}` sets
  `completed_at`; back to `open` clears it.
- `tests/test_frontend_smoke.py` / `test_frontend_library.py` — `node --check`;
  card renders a button.
- Migration up/down.

---

## Phase 2 — Default-today + roll-forward

### 2.1 Writer: bare task defaults to due today

`persist/writer.py`, in the record loop, after computing `kind`:

```
due = ground(rec.due_phrase, now).value
occurred = ground(rec.when_phrase, now).value
if kind in _STATUS_KINDS and due is None and occurred is None \
        and not rec.recurrence_phrase and not _is_someday(rec):
    due = _start_of_day(now)          # deterministic, local midnight
```

- `_is_someday(rec)` — true if `rec.when_phrase`/`rec.due_phrase` matches
  `someday | eventually | some ?point | no rush | whenever | one day` (regex,
  no model). Such tasks stay dateless (a real backlog).
- `_start_of_day` reuses `resolve/dates` helpers (already have `_noon` /
  `_start`-style utilities).

### 2.2 Read-time roll-forward

The problem: a `time_window` of `{start: today, end: today}` on a "what's due
today" query would exclude yesterday's still-open task. Fix in
`query/compile.py::compile_structured`:

- When `sq.status_filter` includes `"open"` **and** the subquery targets
  records **and** there is a `time_window` whose `end` is today or later:
  replace the lower bound with "no lower bound" for rows that are
  `status="open"` — i.e. `((status = 'open' AND due_at <= :end) OR
  (recency BETWEEN :start AND :end))`.
- Equivalent, simpler framing: **an open status-kind record with
  `due_at <= now` is always in-window.** Implement as an OR clause guarded by
  `status_filter` so it only fires on task-shaped queries, never on "what
  happened last week".

`prompts/plan.txt`: a rule — for "what do I need to do / what's on my plate /
tasks" questions, set `status_filter: ["open"]` and leave `time_window` null
(the roll-forward rule handles currency); only set a `time_window` when the
user names one ("due this week").

### 2.3 Ranking / sort

`query/rank.py` (or the `_project` sort): open tasks sorted by `due_at` ascending
(most overdue first), dateless backlog last. Overdue gets a small score bump so
it leads the `TaskListCard`.

### 2.4 Card / phrasing

- `TaskListCard` items already carry `due`; frontend shows "OVERDUE" (red) when
  `due < now` and `status="open"`.
- `respond.py` `rows_to_json`: include a derived `overdue: true` and a
  human `due_label` ("today", "2 days ago", "Fri") so the phrasing model can
  say "you're 2 days late on X" without doing date math.

### Phase 2 tests

- `tests/test_persist_writer.py` — bare task → `due_at == start of today`;
  "someday" task → `due_at is None`; task with "Friday" → grounded to Friday,
  no override; `event` / `gym_session` → never defaulted.
- `tests/test_query_compile.py` / `test_query_pipeline.py` — a task due
  yesterday, still open, appears in a "what's due today" plan; a done task does
  not; "what happened last week" does **not** pull in an open overdue task.
- `tests/test_query_respond.py` — `overdue` / `due_label` in the serialized row.

---

## Phase 3 — Collections registry (storage + learning)

### 3.1 Schema: `collections`

Migration `0009_collections`:

```
collections(
  id              serial pk,
  name            text not null,             -- display: "watchlist"
  kind_slug       text not null unique,      -- the records.kind these items use
  item_noun       text,                      -- "movie or show", "book", "gift idea"
  synonyms        jsonb not null default '[]',  -- ["movies to watch","shows to watch","films i want to see"]
  field_hint      jsonb not null default '{}',  -- {"checkable": true, "fields": ["title","medium","note"]}
  example_record_id integer null references records(id) on delete set null,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
)
index ix_collections_kind_slug (unique, above)
```

ORM model `Collection` in `db/models.py` matching the migration.

`field_hint.checkable` — whether items in this list have an open/done state
(a "to watch" list: yes; a "restaurants I like" list: no). Drives whether
Phase 1's `close_record` considers the kind and whether the card shows
checkboxes.

### 3.2 Extraction schema: the `collection` field

`io_assistant/extract/schema.py` — `SCHEMA_JSON` gains one optional key on a
record:

```
"collection": {"name": str, "item_noun": str, "synonyms": [str],
               "checkable": bool} | null
```

Guidance in the hint: *"Set `collection` only when this record is an item the
user is adding to a personal list that does not fit `event`/`task`/`chore`
(things to watch, books to read, gift ideas, places to try). Use the same
`kind` slug you would use to retrieve the whole list. Fill it on the first item;
you may omit it on later items with the same `kind`."*

One new few-shot example:

```
INPUT: add Dune Part Two to my list of movies I want to watch
OUTPUT: {... records:[{"kind":"watchlist","domain":"other",
  "title":"Dune Part Two","status":"open",
  "collection":{"name":"watchlist","item_noun":"movie or show",
    "synonyms":["movies to watch","shows to watch","watchlist"],"checkable":true},
  "attributes":{"medium":"movie"},"confidence":0.9}]}
```

`ExtractedRecord` (models_domain.py) gains `collection: ExtractedCollection | None`.

### 3.3 Deterministic upsert

`persist/writer.py`, after a record with `rec.collection` is written:

```
upsert_collection(session, slug=normalize_kind(rec.kind), proposal=rec.collection,
                  example_record_id=row.id)
```

`io_assistant/collections/registry.py`:

- `upsert_collection(...)` — insert if `kind_slug` is new; if it exists, merge
  synonyms (union, deduped, lowercased), keep the earliest `name`/`item_noun`
  unless currently null, refresh `updated_at`, set `example_record_id` if null.
- `describe_collections(session) -> str` — compact lines for prompt injection:
  `- watchlist — movies/shows to watch (say: "watchlist", "movies to watch")`.
- `resolve_collection(session, phrase) -> Collection | None` — exact slug, then
  synonym exact, then trigram/fuzzy over name+synonyms. Pure SQL + rapidfuzz.
- `checkable_kinds(session) -> set[str]` — for Phase 1 / card logic.

Items are still plain `records`. The registry is metadata, not a container.

### 3.4 `status` for collection items

A `checkable` collection's items are written with `status="open"` (extend
`_STATUS_KINDS` behavior: `status` defaults to `"open"` when
`kind in checkable_kinds(session)` too). Non-checkable collections: `status`
stays null. `close_record` (Phase 1) already restricts to open + status kinds,
so "I watched Dune" closes the watchlist item.

### Phase 3 tests

- `tests/test_collections_registry.py` — first item creates the row; second
  item with the same slug merges synonyms, does not duplicate; a proposal with
  a conflicting `name` keeps the original; `resolve_collection` hits on slug /
  synonym / fuzzy; `describe_collections` format.
- `tests/test_persist_writer.py` — storing "add X to my movies to watch"
  creates a `watchlist` record **and** a `collections` row; a checkable item
  gets `status="open"`.
- `tests/test_extract_schema.py` — the new few-shot OUTPUT parses as
  `ExtractionResult`.
- Migration up/down.

---

## Phase 4 — Collections-aware routing

### 4.1 Inject the registry into prompts

- `query/planner.py` / the backend `plan` call: prepend
  `describe_collections(session)` to the plan context (above conversation
  history), labelled `Known lists:`. `prompts/plan.txt` gains a rule: *"If the
  question is about one of the Known lists above, set `target_type: "record"`
  and `kind_filter` to that list's slug. Reuse the exact slug — never invent a
  new one."*
- `decide.txt` / `extract` context: same injection, so a new item on an
  existing list reuses the slug ("also add Oppenheimer" → `kind: "watchlist"`).
- The injection is `session`-dependent, so `QueryPipeline.answer` /
  `Orchestrator` pass the rendered string through the existing `context`
  parameter (extend `render_context` to take an optional `preamble`, or
  concatenate before calling). Keep it under ~12 lines / top 20 collections.

### 4.2 Retrieval for "what's on my <list>"

With `kind_filter` set correctly by 4.1, the existing structured path returns
the list. `aggregation: "list"` → all items; `"count"` → "you have 14 movies on
your watchlist" (needs the Plan-2 follow-up `func.count()` branch in
`compile_structured` — pull that small item into this phase since it is the
natural fit). Open vs done split in the answer for checkable lists ("11 to
watch, 3 watched").

### 4.3 Fallback vocabulary

When `collections` is empty or misses, also feed the planner the top ~15
`SELECT kind, count(*) FROM records GROUP BY kind ORDER BY count DESC` slugs
(excluding the core kinds) as a plain `Seen kinds:` line — cheap reinforcement
so even an unregistered list tends to reuse its slug.

### Phase 4 tests

- `tests/test_query_pipeline.py` — seed a `watchlist` collection + 5 items;
  "what's on my watchlist" / "what movies do I want to see" / "films I haven't
  watched yet" all return the 5 (or the 3 open); planner reuses the slug.
- `tests/test_decide_*` / `tests/fixtures/decide_cases.json` — a "add X to my
  <list>" case routes to `store` with the registered slug; a "what's on my
  <list>" case routes to `query` with `kind_filter`.
- `tests/test_query_compile.py` — `aggregation: "count"` → count query.

---

## Phase 5 — Collection surfaces

### 5.1 `CollectionCard`

`models_domain.py` — `CollectionCard { type: "collection", name, item_noun,
kind_slug, checkable, items: [{record_id, title, status, attributes_subset}] }`.
`orchestrator_cards.query_cards` emits it when the answer's rows are all one
registered collection kind. `frontend/components/card.js` — a titled list;
if `checkable`, each row has the same interactive check button as `tasklist`;
an inline "+ add" field posts a normal utterance ("add <text> to my <name>").

### 5.2 Records browser filter

`views/records.js` — the domain filter row gains the registered collection
names as filter chips (`kind_slug` filter). A collection chip shows
open/done counts.

### 5.3 `io list` CLI (optional, thin)

`io list` → the registered collections + counts. `io list <name>` → items.
Read-only; reuses `resolve_collection` + a structured query. Skip if it grows
past ~40 lines.

### Phase 5 tests

- `tests/test_frontend_library.py` / smoke — `CollectionCard` renders, check
  button present when `checkable`.
- `tests/test_orchestrator_*` — a "what's on my watchlist" turn returns a
  `CollectionCard`.
- `tests/test_cli.py` — `io list` (if built).

---

## Cross-cutting

### Config

No new config keys. The feature is always on (it is core life-management, not an
opt-in integration like web). Behaviour with `provider="local"` is identical —
the extra prompt context is small and the close/registry paths are pure Python.

### Migrations

Two new migrations, in order, `down_revision` chaining from the current head
(`0007`): `0008_task_completion` (`records.completed_at`) then `0009_collections`
(`collections` table). Phases 2, 4, 5 add no schema. Renumber if the branch
lands other migrations first.

### Knowledge / docs

- New `.claude/knowledge/tasks-and-collections.md` — the close path, the
  roll-forward rule, the registry, where prompts get their vocabulary.
- Update `.claude/knowledge/query-pipeline.md` (roll-forward, `kind_filter`
  from the registry) and `data-model.md` (`completed_at`, `collections`).
- `.claude/state/backlog.md` / `completed.md` per session.

### Deferred (explicitly out of scope)

- Per-instance completion of a recurring `chore` — completing one marks the
  whole series `done` (which stops it). Instance-level "done this week" needs an
  occurrences table; note it.
- Typed / validated collection fields (the `field_hint.fields` list is advisory
  only in this spec).
- Collection sharing / export.
- A true notification/nag (push, badge) for overdue tasks — this spec makes
  them *surface in queries*, not *interrupt*.
- Snooze / "not today" on a defaulted task (would set `due_at` forward
  explicitly) — small follow-up.

## Success criteria

1. "I need to call the dentist" → stored open, due today. Tomorrow, "what do I
   need to do" lists it as 1 day overdue. "I called the dentist" → that row is
   closed, no duplicate, and it drops out of the list.
2. "add Dune Part Two to my movies to watch" → a `watchlist` record + a
   `collections` row. "also add Oppenheimer" → second item, same slug, no new
   collection. "what's on my watchlist" a week later → both, reliably, however
   the question is phrased. "I watched Dune" → Dune marked done; "what haven't I
   watched" → Oppenheimer only.
3. The model never emits SQL, never picks a record id, never writes a status;
   every test in `tests/` that asserts the LLM boundary still passes.
4. Full suite green against real Postgres; `provider="local"` path unaffected.
