# Current session

Phase 1 complete (Plans 1-4). `.env` loading wired into cli + service
(`io_assistant/_env.py`). Verified end-to-end against the real Anthropic
subscription backend: STORE + QUERY via `io store` / `io repl` / `io serve`.

Three live-run quality fixes landed 2026-09-08:
- router prompt + expanded held-out fixture (21/21 on Haiku)
- bare day words ("today"/"tomorrow"/"last Friday") snap to local noon
- `scrub_roles()` drops bare role nouns ("dentist", "my boss") from people

Full suite 174 pass / 5 opt-in skipped (all on `main`).

One command for the whole stack: **`.\dev.ps1 up`** / **`.\dev.ps1 down`**
(also `status` / `logs` / `app` / `listen` / `doctor` / `test [args]`).
Runtime state in `.io-dev/` (gitignored).

To run voice: `uv run python -m piper.download_voices en_US-amy-medium
--data-dir ~/.local/share/io/piper`, then `.\dev.ps1 up` + `.\dev.ps1 listen`.
`io doctor` is green except Piper (voice model not downloaded).

Remaining work: backlog follow-ups only. Tests need `IO_TEST_DATABASE_URL`
exported; DB is docker compose Postgres+pgvector :5432.
