# Current session

Plan 2 (query pipeline) complete — 141 pass / 3 opt-in skipped, merged into
`main`. QUERY path answers end-to-end via `io_assistant/query/`.

Next: Plan 3 (FastAPI + pywebview desktop, spec §7), then Plan 4 (voice:
faster-whisper in, Piper TTS out — mandatory female voice, a NEW requirement
past spec §6). Write each plan (`writing-plans`), review, execute.

Working on `main` directly (trunk-based, per user). Tests need
`IO_TEST_DATABASE_URL` exported; DB is docker compose Postgres+pgvector :5432.
Backend is `provider = "anthropic"` (Haiku) — needs a credential to actually run.
