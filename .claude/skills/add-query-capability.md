# Skill: add a query capability

The query pipeline lives in `io_assistant/query/` (see
`.claude/knowledge/query-pipeline.md` for the module map). To support a new
question shape:

1. **Planner** — if the model needs to emit a filter it doesn't yet, add it to
   `SubQuery` in `query/plan.py`, document it in `io_assistant/prompts/plan.txt`,
   and ground/clamp it in `ground_plan()` (never trust the raw value —
   time windows go through `resolve.dates.ground`, vocab through
   `normalize_kind`/`normalize_domain`).
2. **SQL compiler** — add the `WHERE`/join in `compile_structured()`
   (`query/compile.py`). Keep it parameterized; keep the `LIMIT 200` cap.
3. **Retrieval** — only if the capability introduces a new `target_type` /
   table: extend `_TARGET_MODEL`, `recency_column`, and the link map.
4. **Ranking** — if a new target type needs a different recency column, extend
   `_recency_value` / `recency_column`.
5. **Fixtures + tests** — add a case to `tests/fixtures/questions_plan.json`
   (raw model output → expected grounded `QueryPlan`), a `test_query_compile.py`
   case (subquery + seeded rows → expected rows), and extend
   `tests/test_e2e_query.py` if it's a user-visible scenario.
6. **Never** let a model-produced value reach SQL unclamped — that is the
   `.claude/rules/llm-boundaries.md` line.

Deferred capability: `aggregation` (`count` / `latest`) is carried on `SubQuery`
but not yet pushed into SQL — a `count` question currently returns the row list
and the Responder counts. Implementing it means a `func.count()` / `LIMIT 1
ORDER BY recency` branch in `compile_structured()`.
