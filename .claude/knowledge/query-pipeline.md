# Query pipeline (hybrid structured + RAG)

**Implemented in Plan 2** — not built in Plan 1. This is a reference summary so a
Plan 1 session understands where its data will be read from.

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
