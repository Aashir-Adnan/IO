# Tasks & Collections

**Implemented (spec `docs/superpowers/specs/2026-09-10-tasks-and-collections-design.md`,
26 tasks / 5 phases, 2026-09-10-11, branch `io-window-glass`).** Closes two
gaps: tasks never closed themselves, and ad-hoc lists ("movies to watch")
fragmented across differently-worded kinds. Ledger with every deviation and
review finding: `.superpowers/sdd/2026-09-10-tasks-and-collections/progress.md`.

## Completion — the `close_record` path

`io_assistant/tasks/complete.py`:
- `set_record_status(session, record, status, now)` — **the one place**
  `record.status` changes. `status == "done"` stamps `completed_at = now`
  (once — doesn't overwrite an existing stamp); `status == "open"` clears it.
  Called from the chat close flow, `PATCH /record/{id}`, and nowhere else.
- `close_record(session, phrase, now, *, checkable_kinds, target_status="done") -> CloseOutcome`
  — pure `rapidfuzz.fuzz.WRatio` match of `phrase` against the `title` of every
  `status="open"` record whose `kind` is in `checkable_kinds`. One SELECT, no
  model, no embedder, never mutates. `CloseOutcome.status` is `"matched"`
  (top score ≥ 72 and ≥12 ahead of #2 — return `.record`), `"ambiguous"`
  (score ≥ 55 — return up to 3 `.candidates`, in descending fuzz-score
  order), or `"none"`.

Two entry points reach it, both in `io_assistant/orchestrator.py`:

1. **Precheck** (`_complete_precheck(text) -> "done" | "dropped" | None`,
   backend-agnostic, runs before planning on every non-confirmed turn) — regex
   families `_COMPLETE_DONE` / `_COMPLETE_DROP`, gated by `_COMPLETE_QUESTION`
   (a question never completes anything) and `_COMPLETE_MAX_WORDS = 12`. A hit
   calls `_try_complete`, which strips the completion verb via
   `_completion_phrase(text)` and calls `close_record`. `_DEFINITE` requires
   the object be definite ("the report", "my dentist thing") — "I finished a
   book last night" is new information, not a close, and falls through to
   store.
2. **`complete_record` capability** (`io_assistant/actions/registry.py`,
   combined-decide mode only) — args `{what}`. Handler
   `_action_complete_record` calls the same `_try_complete`, phrase from
   `args["what"]` or falling back to `_completion_phrase(text)`.

`_checkable_kinds(session)` (orchestrator) = `{"task", "chore"} |
checkable_kinds(session)` (the registry — see below), so a watchlist item
closes through the same path.

**Ambiguity gate**: `_try_complete` re-sorts `out.candidates` from
score-order to **id order** (oldest-first — so "the first one" means the
first one listed, and the numbering is stable across calls) before
numbering them for the gate, then returns `intent_kind="gate"` with a
`PendingComplete(candidate_ids, target_status)` and a numbered prose list.
The next turn — matched via `isinstance(pending, PendingComplete)` in
`_handle_in_session` — resolves **in Python**: `_resolve_completion` re-checks
every candidate is still `status="open"` (re-gates with a fresh numbered list
if any closed since, so stale numbering never mispicks) then
`_pick_candidate(reply, rows)` (ordinal word → `_ORDINAL_WORDS`, "last", a
bare digit, else fuzzy title match, `>=60` and clearly ahead) calls
`set_record_status`. No model call on this turn.

`target_status` also carries `"dropped"` through the same path (regex only —
`complete_record` the capability can't currently express dropped; see
Deferred below).

## `records.completed_at`

Migration `0008_task_completion` — `TIMESTAMPTZ NULL`, maintained only by
`set_record_status`. See `.claude/knowledge/data-model.md`.

## Default-today + roll-forward

`io_assistant/resolve/dates.py`:
- `start_of_day(d)` — local midnight; the default `due_at` for a bare task.
- `is_someday_phrase(text)` / `_SOMEDAY` regex — "someday", "eventually",
  "no rush", "whenever", etc. A phrase matching this is a **groundable "no
  date"** (`DateResult(None, True)`), not an ungroundable failure — unless the
  same phrase also carries a real date token (`_DATEISH`, now including
  weekday names: "by Friday, no rush" still grounds to Friday). `ground()`
  checks this before its normal dispatch.

`io_assistant/persist/writer.py`, in the per-record loop:
```
if kind in _STATUS_KINDS and due is None and occurred is None \
        and not rec.recurrence_phrase and not _is_someday(rec):
    due = start_of_day(now)
```
`_is_someday(rec)` = `is_someday_phrase(rec.when_phrase) or
is_someday_phrase(rec.due_phrase)`. Only `task`/`chore` (`_STATUS_KINDS`) are
touched — `event`, `gym_session`, etc. are never defaulted.

**Read-time roll-forward** (no daily job) — `io_assistant/query/compile.py`,
both `compile_structured` and `compile_count`: when the subquery targets
`record`, `status_filter` includes `"open"`, and a `time_window` is present,
the window clause becomes
`OR(window, AND(status == "open", due_at <= now))` — an overdue open record is
always in-window regardless of the window's lower bound. Guarded on
`status_filter` so it never fires on "what happened last week". The two
compile functions share kind/domain/status/entity filtering via `_conds()`;
each keeps its own copy of the time-window + roll-forward block (a deliberate
non-DRY choice — see `_conds()`'s docstring).

`prompts/plan.txt` tells the model: for "what do I need to do" style
questions, set `status_filter: ["open"]` and leave `time_window` null (the
roll-forward rule supplies currency); only set a window when the user names
one.

**Ranking** — `io_assistant/query/rank.py::rank()`: an open record whose
`due_at < now` gets a flat `+0.2` added to its score (`overdue` component),
on top of the existing recency/similarity/structured/provenance blend, so
overdue items surface ahead of merely-fresh ones.

**Phrasing** — `io_assistant/query/respond.py::rows_to_json()` adds
`overdue: bool` (`status == "open" and due_at is not None and due_at < now`)
and `due_label: str | None` (`_due_label` — "today"/"tomorrow"/"yesterday"/"N
days ago"/weekday abbrev/`"%a %d %b"`) to every row, computed in Python so the
phrasing model never does date arithmetic. `section_for(status)` returns
`"done"` or `"to_do"`, attached as `d["section"]` **only when
`status is not None`** (a plain past event/note has `status=None` and must
never be mislabelled a to-do).

## Collections registry

Migration `0009_collections` — `collections(id, name, kind_slug UNIQUE,
item_noun, synonyms jsonb, field_hint jsonb, example_record_id fk->records
ON DELETE SET NULL, created_at, updated_at)`. ORM `Collection` in
`io_assistant/db/models.py`. `field_hint.checkable` — whether items have an
open/done state (a "to watch" list: yes; "restaurants I like": no).

**Extraction**: `ExtractedRecord.collection: ExtractedCollection | None`
(`io_assistant/models_domain.py`) — `{name, item_noun, synonyms, checkable}`.
The model proposes this once per novel list (`io_assistant/extract/schema.py`
guidance: set only for a personal list that doesn't fit `event`/`task`/
`chore`; reuse the kind slug you'd use to retrieve the whole list; may omit on
later items with the same kind).

**`io_assistant/collections/registry.py`** (pure Python — no model calls):
- `upsert_collection(session, *, kind_slug, proposal, example_record_id, now) -> Collection`
  — insert on a new `kind_slug` (normalized via `normalize_kind`); on an
  existing row, union+dedupe `synonyms` (lowercased), fill `item_noun` only if
  currently empty, `field_hint["checkable"]` set via `setdefault` (first
  proposal wins), fill `example_record_id` only if null, refresh
  `updated_at`.
- `describe_collections(session) -> str` — one line per collection (created_at
  order, capped `_MAX_LINES=20`): `- watchlist — movie or show (say: "watchlist", "movies to watch", ...)`.
  Empty string when there are no collections.
- `resolve_collection(session, phrase) -> Collection | None` — exact
  `kind_slug`/synonym match first, else best `rapidfuzz.WRatio` over
  name+synonyms if `>= 82` (`_FUZZY`).
- `checkable_kinds(session) -> set[str]` — every `kind_slug` whose
  `field_hint.checkable` is true.
- `seen_kinds(session, *, limit=12) -> list[str]` — non-core (`_CORE_KINDS`)
  `records.kind` slugs by row count, most common first — fallback vocabulary
  even for a list the model never flagged as a collection.
- `routing_preamble(session) -> str` — `describe_collections` (as "Known
  lists (reuse the exact slug):") + `seen_kinds` (as "Seen kinds: ..."),
  joined; `""` when both are empty.

**Writer** (`io_assistant/persist/writer.py`): after computing `kind`,
`checkable = kind in _STATUS_KINDS or kind in checkable_kinds(session) or
(rec.collection is not None and rec.collection.checkable)`; a checkable
record with no explicit `status` defaults to `"open"`. After the row is
flushed, `if rec.collection is not None: upsert_collection(...,
example_record_id=row.id)` registers/updates the list. The
`checkable_kinds`/`upsert_collection` import sits **inside** `_write()` to
avoid a circular import between `persist` and `collections` (noted, accepted).

## Where `describe_collections`/`routing_preamble` are injected

Both injection sites use `routing_preamble(session)`, prepended to whatever
history/context string is already being built:
- **Orchestrator plan/decide context** — `_handle_in_session`:
  `decide_ctx = routing_preamble(session) + (history or "") or None`, passed
  to `DecidePlanner.plan(...)`.
- **Query planner context** — `QueryPipeline.answer`:
  `plan_ctx = routing_preamble(session) + (context or "") or None`, passed to
  `Planner(...).run(...)`.

`prompts/plan.txt` and `decide.txt` both carry a rule: if the question/item is
about one of the "Known lists" shown, reuse that list's exact `kind_filter`/
`kind` slug — never invent a new one.

## `checkable_kinds` and the interactive checkbox / card

`orchestrator._checkable_kinds` = `{"task", "chore"} | checkable_kinds(session)`.
Frontend `card.js::wireChecks(root, ctx)` (shared by the `tasklist` and
`collection` branches) wires every `.task-check` button to
`ctx.api.editRecord(id, {status: nextStatus})` with optimistic toggle + revert
on error — no new endpoint, `PATCH /record/{id}` covers it end to end via
`set_record_status`.

## `CollectionCard`

`models_domain.py::CollectionCard { type: "collection", name, item_noun,
kind_slug, checkable, items: [TaskListItem] }`. Emitted by
`orchestrator_cards.py::query_cards`: when `answer.list_records` are all one
`kind` **and** that `kind_slug` has a registered `Collection` row, a
`CollectionCard` is appended and the function returns early (it replaces, not
supplements, the generic `TaskListCard`). Otherwise the existing
`TaskListCard` widening applies: emitted when at least half the list rows are
status-bearing (`status` set or `due` set). `SourcesCard` is always appended
first regardless of which list-card branch fires.

`frontend/components/card.js`'s `collection` branch renders a titled list; a
checkable collection gets the same `.task-check` buttons as `tasklist`
(via `wireChecks`); an inline add field posts a plain utterance ("add <text>
to my <name>") through `ctx.onAsk`.

## Retrieval: `count` aggregation

`SubQuery.aggregation: "list" | "count" | "latest"` (only `list`/`count`
compiled today). `io_assistant/query/retrieve.py`: a `count` subquery runs
`compile_count` and returns a single synthetic `_Count(count)` carrier row
(`id = -1` class attribute as a belt-and-suspenders guard). `pop_count(rows)`
splits `(count, remaining_rows)` and **must** be called immediately on the raw
`retrieve_subquery` result, before `rank()` — a `_Count` has no date to score
and would otherwise be merged/recurrence-expanded like a real row.
`QueryPipeline.answer` calls `pop_count` per-subquery, collects `count`, and —
if any subquery returned one — phrases via
`Responder.run(question, data_rows, shape, now=, context=, force=True)`.
`force=True` bypasses the usual "no rows → deterministic empty answer"
short-circuit (a pure count has zero list rows by construction).
`QueryAnswer.count: int | None` carries it out of the pipeline (no card
currently reads it — text-only today).

## Surfaces

- `GET /collections` (`service/app.py`) — every collection with live
  `open_count`/`done_count` (`SELECT count(*) ... WHERE kind = c.kind_slug AND
  status = ...`).
- `frontend/views/records.js` — filter chips from `ctx.api.collections()`,
  each showing `open/total`.
- `io list` (`io_assistant/cli.py`) — bare: every collection + live
  open/done counts (same query shape as `GET /collections`, kept in sync
  deliberately). `io list <name>`: `resolve_collection` then every record of
  that `kind_slug`, done-last, `[x]`/`[ ]` prefixed. Read-only, no model.

## Deferred (see `.claude/state/backlog.md` for the full consolidated list)

- Per-instance completion of a recurring `chore` — completing one instance
  currently marks the whole series `done` (stops it); true instance-level
  completion needs an occurrences table (spec, explicitly out of scope).
- Typed/validated collection fields — `field_hint.fields` is advisory only.
- Collection sharing/export.
- A real notification/nag for overdue tasks — this feature makes them surface
  in queries, not interrupt.
- Snooze / "not today" on a defaulted task.
- Completion-verb vocabulary gap — "I watched X" / "I read X" don't close a
  watchlist/reading-list item yet (`_DONE_VERB` has no watch/read synonyms).
- `close_record`'s `none` branch doesn't fall through to the planner (a false
  completion precheck on an untracked thing stores nothing, loses the note).
- `complete_record` can't express "dropped" via the model (the capability
  route always defaults to `"done"`; only the regex precheck can drop).
