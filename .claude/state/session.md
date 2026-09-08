# Current session

Plans 2 (query pipeline), 3 (FastAPI service + pywebview desktop), and 4 (voice
— Whisper in, Piper female TTS out, `io listen`, `io doctor`) all complete —
170 pass / 5 opt-in skipped, all on `main`. Spec §6.1 (spoken output) added.

**Phase 1 is functionally complete**: typed/GUI/voice all converge on the one
Orchestrator; STORE and QUERY end-to-end; spoken answers.

To actually run the full loop you need:
- a backend credential (`claude setup-token` → `ANTHROPIC_AUTH_TOKEN` in `.env`,
  or switch `[backend].provider` back to `local`);
- `uv run python -m piper.download_voices en_US-amy-medium --data-dir ~/.local/share/io/piper`;
- `uv run io serve` then `uv run io listen` (needs a mic).
`uv run io doctor` reports what's missing.

Remaining work is all backlog follow-ups (see backlog.md) — no more planned
phases. Tests need `IO_TEST_DATABASE_URL` exported; DB is docker compose
Postgres+pgvector :5432.
