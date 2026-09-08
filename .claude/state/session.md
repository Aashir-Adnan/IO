# Current session

**Phase 1.5 (conversational shell) COMPLETE** — Plans 5 + 6 both done, on
`main`. Full suite **199 pass / 8 opt-in skipped**. See completed.md.

- Plan 5: conversation memory, natural `acknowledge`, `/voice` + natural Piper,
  `/entity` (Memory Inspector), `/standby`, `TurnResponse`/cards.
- Plan 6: `frontend/` rebuilt in the Nocturne design system (vendored fonts +
  Phosphor + tokens, no CDN). Shell + Standby / Listening / Conversation views +
  orb + simulated typing + conversations drawer. `open_window(url, *,
  fullscreen)` with remembered window geometry + native menu.

**Verified:** node pure-JS tests, asset lint, local-first socket guard, live
browser smoke against the real Anthropic backend (earlier this session).
**Not verified here:** Playwright DOM smoke (`-m ui`, needs `uv run playwright
install chromium`); the pywebview window on a real display; voice end-to-end
(needs mic + downloaded Whisper/Piper models).

**Next — pick from backlog.md.** Top candidates:
- state 1d task runner (agent loop + approval gates + live log)
- `/ws` token streaming (typing would then reflect real generation)
- external-source provenance; entity-file browser (Timeline/Sources/Review stubs)
- Kokoro `Speaker` adapter; ISO/absolute date grounding

Tests: `.\dev.ps1 test`. DB = docker compose :5432. Voice end-to-end:
`uv run python -m piper.download_voices en_US-hfc_female-medium --data-dir
~/.local/share/io/piper`, then `.\dev.ps1 up` + `.\dev.ps1 listen`.
