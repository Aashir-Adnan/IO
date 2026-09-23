# Query pipeline (hybrid structured + RAG)

**Implemented (Plan 2, 2026-09-08).** Runs when Route returns `QUERY`.

Modules in `io_assistant/query/`:
- `plan.py` — `SubQuery`/`QueryPlan` pydantic + `ground_plan(raw, now)`:
  clamps time windows (via `resolve.dates.ground`), normalizes kind/domain
  vocab, drops unknown domains, coerces bad enums, synthesizes one bare
  subquery when the model returns none.
- `planner.py` — `Planner.run()`: `backend.plan` → `ground_plan`, retry once,
  fall back to a single `semantic_hint=question` subquery.
- `entities.py` — `resolve_query_entities()`: unresolved names → `{etype: [ids]}`
  via `EntityResolver.lookup()` (read-only, no create/gate) + occasion name match.
- `compile.py` — `_conds(sq, entity_ids)` shares kind/domain/status/entity
  filters between the two compile functions (never touches time).
  `compile_structured(sq, entity_ids, now)` → SQLAlchemy `Select` over the
  target table; `EXISTS` subqueries for entity links; window on
  `coalesce(occurred_at, due_at, created_at)`; `LIMIT 200`. **Read-time
  roll-forward** (Tasks & Collections): when `sq.target_type == "record"` and
  `"open" in sq.status_filter`, the time-window clause becomes
  `OR(window, AND(status=="open", due_at<=now))` — an overdue open task/chore
  is always in-window, guarded so it never fires on a status-less query like
  "what happened last week". `compile_count(sq, entity_ids, now)` — same
  `_conds()` + its own copy of the roll-forward block, returns
  `SELECT count(*)`. See `.claude/knowledge/tasks-and-collections.md`.
- `retrieve.py` — `retrieve_subquery()`: structured spine ∪ pgvector KNN
  (`LIMIT 50`, same target + window), provenance `structured`/`semantic`/`both`.
  `sq.aggregation == "count"` short-circuits to a single synthetic `_Count`
  carrier row instead of running the structured+semantic union;
  `pop_count(rows)` extracts `(count, remaining_rows)` and must run before
  `rank()` (a `_Count` has no date to score and must never be merged or
  recurrence-expanded).
- `rank.py` — `rank(groups, now, top_n=20)`: `score = 0.30*recency +
  0.30*similarity + 0.30*structured_relevance + 0.15*(provenance=="both") +
  0.2*(status=="open" and due_at<now)`. `recency = exp(-age_days/30)`,
  `similarity = 1-distance`, `structured_relevance = 1.0` unless semantic-only
  (`0.4`); the `+0.2` overdue bump surfaces overdue open tasks ahead of merely
  fresh rows.
- `recur.py` — `expand_recurrences()`: `dateutil.rrule` firings in the window
  (cap 50); unparseable rules pass through.
- `respond.py` — `Responder.run(question, rows, shape, *, now, context, force=False)`:
  empty rows → deterministic "I don't have anything on that yet." (no model
  call) unless `force=True` (the count path, which legitimately has zero list
  rows); else `backend.phrase(question, rows_to_json(rows, now), shape,
  context=context)`. `rows_to_json` adds `overdue: bool` and `due_label: str|None`
  to every row (Python date math, never the model's) and `section` (`"to_do"`/
  `"done"`, only when `status is not None`) via `section_for(status)`.
- `pipeline.py` — `QueryPipeline.answer(session, question, now, *, context)`
  wires it all; prepends `collections.registry.routing_preamble(session)` to
  `context` before planning (the "Known lists" / "Seen kinds" vocabulary — see
  `.claude/knowledge/tasks-and-collections.md`) so `kind_filter` reuses a
  registered list's exact slug. Pops `_Count` carriers per-subquery via
  `pop_count` before `rank()`; if any subquery counted, phrases through
  `Responder.run(..., force=True)` and returns `QueryAnswer.count: int | None`.
  `Orchestrator` builds one and the `intent == "query"` branch calls it (logging
  the utterance with `resolved_intent="query"`).

Deferred: `aggregation: "latest"` is parsed onto `SubQuery` but not yet
special-cased in `compile.py` (`list`/`count` are compiled).

--- (original spec summary follows) ---

Runs when Route returns `QUERY`.

**Plan** — the model converts the question into a `QueryPlan`: a list of
`subqueries`, each with `target_type` (`record` | `person` | `place` |
`occasion`), `kind_filter`, `domain_filter`, `entities` (unresolved names),
`time_window`, `status_filter`, `semantic_hint`, `aggregation` (`list` | `count`
| `latest`); plus `answer_shape` (`text` | `markdown` | `diagram`). Time windows
and the `kind`/`domain` vocabulary are grounded / clamped by app code, never
trusted raw. A simple question produces a single subquery and skips planning
overhead where possible.

**Retrieve — both paths, every subquery** — Structured: the filters compile to
one parameterized SQL statement (the authoritative spine). Semantic: if
`semantic_hint` is present, embed it and run a pgvector NN search constrained to
the same `target_type` and time window (never an unbounded scan). Union and
dedupe by row id, tagging provenance (`structured` / `semantic` / `both`).

**Merge & rank** — weighted blend of recency, vector similarity, structured
relevance (explicit due date / direct entity link outranks fuzzy), and
provenance (`both` outranks either alone). Cap at a configurable top-N (default
20).

**Expand recurrences** — for any record or occasion with a `recurrence_rule` in
the window, expand the RRULE to concrete instances with `dateutil.rrule`.

**Phrase** — the Respond model gets only the final ranked rows as JSON plus the
question and `answer_shape`; it answers strictly from the rows, states
explicitly when nothing matched, and emits markdown / a fenced `mermaid` block /
plain text per the shape.

Every retrieval is bounded by a type and (almost always) a time window; HNSW +
b-tree indexes keep both paths sub-linear, so history can grow to years without
degrading latency.
