# Current session

Plans 2 (query pipeline) and 3 (FastAPI service + pywebview desktop) complete —
153 pass / 3 opt-in skipped, all on `main`.

Next: **Plan 4 — voice.** faster-whisper transcribe (in), Piper TTS (out —
MANDATORY, en_US female voice; a NEW requirement beyond spec §6). Also
push-to-talk hotkey, passive/VAD mode, `io doctor`. Needs a spec addendum for
spoken output. The Plan-4 voice client talks to `io serve` over `/ws`;
`io serve` streams the answer text back, the client speaks it via Piper.

Working on `main` (trunk-based). Tests need `IO_TEST_DATABASE_URL` exported; DB
is docker compose Postgres+pgvector :5432. Backend `provider = "anthropic"`
(Haiku) — needs a credential to actually run end-to-end.
