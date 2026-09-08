# Completed (newest first)

## 2026-09-08
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
