# Skill: add a query capability

**Plan 2** — the query pipeline is not built in Plan 1. This file is a
placeholder to be filled in when Plan 2 starts.

Rough shape (from spec §5): support a new question shape by (1) adding planner
few-shots so the model emits the right `QueryPlan` subquery
(`kind_filter` / `domain_filter` / `time_window` / `status_filter` /
`semantic_hint` / `aggregation`), (2) extending the SQL compiler in `query/` if
the subquery needs a filter it does not yet emit, (3) adding planner fixtures
(question → expected `QueryPlan`) and SQL-compilation fixtures (subquery →
parameterized SQL + params, executed against the seeded test DB). Time windows
and `kind`/`domain` vocabulary are always grounded / clamped by app code.
