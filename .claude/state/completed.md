# Completed (newest first)

## 2026-09-08 — Plan 3: local service + desktop shell
`docs/superpowers/plans/2026-09-08-io-phase-3-service-and-desktop.md`, 6 tasks.
`io_assistant/service/`: `create_app()` (FastAPI, one Orchestrator), `/health`,
`POST /utterance` (gate carried via in-memory `pending_token` map), `WS /ws`,
static frontend mounted at `/app`. `frontend/` — vendored ES modules, hash
router, WS client, hand-rolled `vendor/markdown.js` (no CDN, enforced by
`test_frontend_assets.py`); chat active, timeline/sources/review stubbed.
`io serve` (headless) + `io run` (pywebview). Full suite 153 pass / 3 skipped.
`io serve` smoke-tested (health, /app/, assets). Deferred: token streaming,
real Mermaid, off-thread handle, history endpoint.

## 2026-09-08 — Plan 2: query pipeline
`docs/superpowers/plans/2026-09-08-io-phase-2-query-pipeline.md`, 10 tasks.
`io_assistant/query/`: `plan.py` (QueryPlan + ground_plan), `planner.py`,
`entities.py` (+ `EntityResolver.lookup`), `compile.py`, `retrieve.py`
(structured ∪ pgvector), `rank.py`, `recur.py` (RRULE), `respond.py`,
`pipeline.py`. `LocalBackend`/`AnthropicBackend` `plan()`+`phrase()` real.
`Orchestrator` QUERY branch answers + logs (`resolved_intent="query"`).
Spec §9 scenarios 2 & 3 pass e2e. Full suite 141 pass / 3 opt-in skipped.
Deferred: `aggregation` count/latest not pushed into SQL yet.

## 2026-09-08 — Backlog cleanup
Backlog-cleanup plan (`docs/superpowers/plans/2026-09-08-io-backlog-cleanup.md`),
7 tasks: config `embedding_dim` guard; `LocalBackend` wraps malformed Ollama
bodies; `Orchestrator` owns one session per `handle()` (commit + close, no
leak); migration `0002` (aliases `server_default`, drop redundant PK-leading
indexes, `pg_trgm` + trigram indexes); `EntityResolver` narrows candidates in
SQL and honours aliases; `persist_store` resolves record-referenced names and
gates unreadable recurrence. Also this session: cloud backend hookup
(`provider="anthropic"`, Haiku, cached schema prompt, `ANTHROPIC_AUTH_TOKEN`)
and relative-duration date grounding. Full suite 111 pass, 3 opt-in skipped.

Deviations from plan: Task 3 (db-fixture nested-tx rewrite) unnecessary —
SQLAlchemy 2.0 `conditional_savepoint` already isolates `commit()`; kept only
the guard test. Task 5 full ORM index mirroring deferred (backlog); did the
`aliases` `server_default` on the ORM.

## 2026-09-07
Plan 1 (core storage pipeline) — Tasks 0-16 + correctives + final-review fix wave.
STORE pipeline end-to-end: typed utterance → route → extract → resolve → persist
into the open-ended `records` table. `Backend` interface (local Ollama /
Anthropic / hybrid), embeddings always local, confirmation gate, hold-and-replay
on confirm, savepoint-protected writes. Full suite 88 pass, 3 opt-in skipped.
Test schema built from the Alembic migration. Follow-ups in backlog.md.
