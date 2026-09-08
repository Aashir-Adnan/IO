# Current session

**Plan 5 (conversational backend) COMPLETE** — 194 pass / 5 opt-in skipped, all
on `main`. Conversation memory + natural `acknowledge` + `/voice` + natural
Piper + `/entity` + `/standby` all working and tested. See completed.md.

**Next: Plan 6 — Nocturne desktop client**
(`docs/superpowers/plans/2026-09-08-io-phase-6-nocturne-client.md`, 10 tasks).
Rebuild `frontend/` in the Nocturne design system (`docs/design/` — blurple,
Inter + Plex Mono, Phosphor, the orb). Vendor everything (no CDN). Three states:
Standby / Listening / Conversation + Memory Inspector. Simulated typing.
Fullscreen window. Node-run tests for pure JS; opt-in Playwright DOM smoke.

Backlog after 1.5: state 1d task runner, external-source provenance, entity-file
browser, `/ws` token streaming, Kokoro TTS.

Tests: `.\dev.ps1 test`. DB = docker compose :5432. To run voice end-to-end:
`uv run python -m piper.download_voices en_US-hfc_female-medium --data-dir
~/.local/share/io/piper`, then `.\dev.ps1 up` + `.\dev.ps1 listen`.
