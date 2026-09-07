# Completed (newest first)

## 2026-09-07
Plan 1 (core storage pipeline) — Tasks 0-16 + correctives + final-review fix wave.
STORE pipeline end-to-end: typed utterance → route → extract → resolve → persist
into the open-ended `records` table. `Backend` interface (local Ollama /
Anthropic / hybrid), embeddings always local, confirmation gate, hold-and-replay
on confirm, savepoint-protected writes. Full suite 88 pass, 3 opt-in skipped.
Test schema built from the Alembic migration. Follow-ups in backlog.md.
