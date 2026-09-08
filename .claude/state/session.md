# Current session

Executing **Plan 5** (conversational backend) — see
`docs/superpowers/plans/2026-09-08-io-phase-5-conversational-backend.md`.
Spec: `docs/superpowers/specs/2026-09-08-io-phase-1.5-conversational-shell.md`.
Visual system: **Nocturne** — `docs/design/` (adopted; blurple, Inter + Plex
Mono, Phosphor, the orb). Plan 6 (`…-phase-6-nocturne-client.md`) after.

## Plan 5 progress (185 pass / 5 skipped)

- [x] Task 1 — 0003 conversations/messages + ConversationStore + context formatter
- [x] Task 2 — Card domain types + build_fact_list()
- [x] Task 3 — Backend context= on route/plan/phrase + acknowledge()
- [x] Task 4 — Orchestrator threads history, acknowledges, returns cards
- [ ] Task 5 — ConversationStore in the service + TurnResponse
- [ ] Task 6 — POST /voice + /voice/health + lazy Whisper/Piper
- [ ] Task 7 — natural Piper (speech_text + sentence-wise synth)
- [ ] Task 8 — io listen -> POST /voice
- [ ] Task 9 — GET /entity/{etype}/{id} + GET /standby
- [ ] Task 10 — docs + state

Then Plan 6 (10 tasks): vendor fonts/icons/tokens, shell, orb, Standby /
Listening / Conversation+Inspector views, typing, conversations drawer,
fullscreen window.

Backlog after 1.5: state 1d task runner (agent loop), external-source
provenance, entity-file browser, /ws token streaming, Kokoro TTS adapter.

Tests: `.\dev.ps1 test` (sets IO_TEST_DATABASE_URL). DB = docker compose :5432.
Voice default: `en_US-hfc_female-medium` (Piper, tuned + sentence-wise).
