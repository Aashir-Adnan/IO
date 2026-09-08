# Completed (newest first)

## 2026-09-08 — Phase 2A: file index & text exploration
Branch `io-phase-2a-file-index` (not yet merged). Spec
`…-io-phase-2-file-index-design.md`, plan `…-io-phase-2a-file-index.md` (15
tasks). Migration `0004`: `file_nodes` (path_key dedup, content/index-hash
staleness gate, summary+embedding), `file_chunks` (text + embedding + generated
`tsv` FTS), `file_edges` (`contains`/`references`; shares-entity derived),
`file_entity_links` (polymorphic, link-on-resolve only). `io_assistant/files/`:
`AccessGate` (deny-by-default read authority), `walk_dir`, `read_document`
(pypdf/python-docx), `chunk_text`, `FileIndex`, `FileIndexer` (hash-gated —
re-index of unchanged content is a no-op), `classify_file_command` +
`resolve_register_target`, `FileSearcher` (FTS + pgvector + entity + one-hop
graph → rank → lazy re-index → phrase), `IndexQueue`. New coarse `file` router
intent (deterministic register/search split). `Backend.summarize_file` +
`answer_from_files` on all 3 backends + FakeBackend. Orchestrator `_file_turn` /
`_file_register`. Service `/files`, `/files/reindex`, `/files/status`,
`/files/content` (404 when disabled). `io files add/list/reindex/forget/search/
status`. Frontend Files rail view + `files` card + in-app text viewer.
LLM-boundary intact (discovery/rank/freshness/identity all deterministic).
Cloud boundary: file text → Anthropic when provider≠local (embeddings always
local); `io files add` prints the notice. Full suite 267 pass / 9 skip; socket
guard green. Deferred to Spec C: media gallery / thumbnails / video / captions.


## 2026-09-08 — Plan 6: Nocturne desktop client
`docs/superpowers/plans/2026-09-08-io-phase-6-nocturne-client.md`, 10 tasks.
Spec: `…-phase-1.5-conversational-shell.md` §2/§7. `frontend/` rebuilt in the
Nocturne design system: vendored Inter + IBM Plex Mono woff2 + inlined Phosphor
SVGs (`vendor/icons.js`) + `tokens.css` (no CDN, under byte budget). Hand-rolled
`createStore` + `Api` client (REST + auto-reconnect WS). Shell = titlebar +
rail + drawer + `#view`; three views — Standby (greeting/stats/orb/chips/
composer), Listening (mic-live orb, `WavRecorder` → `POST /voice`, VAD/gain),
Conversation (`#thread` + compact composer + Memory Inspector slot; record/
tasklist/sources cards). `Orb` component, 4 modes. `revealText` simulated typing
(`min_think_ms` hold → `typing_cps`, accelerating; instant-complete `cancel()`),
paced from `config.ui`. Conversations drawer (grouped Today/Yesterday/Earlier,
new + history hydrate). Desktop shell: `open_window(url, *, fullscreen)` —
geometry persisted to `~/.local/share/io/window.json`, restored on open;
fullscreen first-run; native menu (New Conversation / Reload / Toggle
Fullscreen). Tests: `test_frontend_assets` (no external URLs, font budget,
`node --check`), pure-JS `markdown`/`typing`/`recorder` via node,
`test_frontend_smoke.py` (`-m ui`, `IO_UI_TESTS=1`) Playwright headless against
the `ui_page` stub-server fixture + `tests/fixtures/ui/*.json`. Full suite
199 pass / 8 opt-in skipped (3 new ui skips — Playwright not installed here;
the `ui` marker + one-time `playwright install chromium` are documented).
**Phase 1.5 complete.**

## 2026-09-08 — Plan 5: conversational backend
`docs/superpowers/plans/2026-09-08-io-phase-5-conversational-backend.md`, 10
tasks. Spec: `…-phase-1.5-conversational-shell.md`. `0003` conversations/messages
+ `ConversationStore` + `format_context`. `Backend` `context=` on
route/plan/phrase + `acknowledge()` (natural STORE reply, restates written facts
only). `Orchestrator` threads history, returns `cards` (record/tasklist/sources)
+ `intent_kind`. Service owns conversations; `/utterance` + `/ws` return
`TurnResponse`; `/conversation(s)`. `POST /voice` + `/voice/health` (lazy
Whisper/Piper via `service/voice.py`). Natural Piper — sentence-wise synth +
`speech_text` prep + tuned `SynthesisConfig`, default `en_US-hfc_female-medium`.
`io listen` refactored to `POST /voice`. `GET /entity/{etype}/{id}` (Memory
Inspector) + `GET /standby`. `UiConfig`. Full suite 194 pass / 5 opt-in skipped;
local-first socket guard still green. Next: Plan 6 (Nocturne desktop client).

## 2026-09-08 — Plan 4: voice (speech in, speech out)
`docs/superpowers/plans/2026-09-08-io-phase-4-voice.md`, 7 tasks. Spec §6.1
addendum (spoken output). `io_assistant/speak/` — `flatten_markdown()` +
`Speaker` protocol + `PiperSpeaker` (en_US-amy-medium female, degrades to
text-only). `transcribe/` — `Transcriber` + `WhisperTranscriber` (size from
profile). `capture/` — `segment_stream()` VAD, `build_utterance()`, audio/hotkey
seams. `voice/` — `ServiceClient` + `VoiceLoop` (`handle_wav`: transcribe →
`POST /utterance` → speak; SpeakError non-fatal). `io listen` (push-to-talk /
`--passive`), real `io doctor` (7 checks). Deps: piper-tts, faster-whisper,
sounddevice, numpy, pynput, webrtcvad-wheels. Full suite 170 pass / 5 skipped
(3 ollama-anthropic + 2 voice opt-in). `io doctor` smoke-run. The real audio
loop needs a mic + downloaded models to verify end-to-end.

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
