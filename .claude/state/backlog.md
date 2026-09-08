# Backlog (highest priority on top)

- ~~Live-run findings 2026-09-08~~ — all three FIXED 2026-09-08:
  router prompt + held-out fixture (21/21 on Haiku); bare day words snap to
  local noon (`_noon` in `resolve/dates.py`); `scrub_roles()` drops role-noun
  "people". Re-verified end-to-end against Haiku.
  Still open: the opt-in `test_router_with_local_backend` floor is 0.7 for
  llama3.2:3b — re-baseline it against the new prompt when convenient.

- Extraction eval quality: `tests/fixtures/utterances_store.json` cases 1-3 & 6
  overlap the few-shot `_EXAMPLES` in `extract/schema.py`, so
  `test_extractor_against_fixtures` partly measures shot reproduction. Add
  several genuinely held-out utterances (varied phrasing, multi-record, negation)
  and re-baseline the pass-rate threshold.
- ~~Deferred minors from Plan 1 review~~ — DONE 2026-09-08 (backlog-cleanup
  plan): field_validator import, aliases server_default (0002), redundant
  PK-leading indexes dropped (0002), malformed-Ollama KeyError wrapped,
  resolver honours caller + stored aliases, persist_store resolves
  record-referenced names, recurrence_phrase gated, items link test added.
- Date grounding vs 3B model: `ground()` returns ok=False for absolute/ISO dates,
  and llama3.2:3b sometimes emits an ISO datetime as `when_phrase` (despite the
  prompt saying "copy the raw phrase") → every such record needlessly gates.
  Fix: (a) `ground()` should parse ISO-8601 and common absolute date strings via
  `dateutil.parser` and return ok=True; (b) tighten the extract prompt /
  post-process to strip model-invented ISO timestamps back toward "today".
  (2026-09-08: relative durations now handled — "N weeks/months/years ago",
  "in N weeks", "a year ago", "last/next month|year", "for N years now". ISO /
  absolute-string parsing still open.)
- CLI hardening (Plan 3/4 or standalone): `io repl` should catch per-line
  exceptions and continue instead of dying; persist `stripped` not raw `line`
  into `Utterance.text` (cli.py); rename `_make_session_factory` (returns a
  tuple); optionally cache the Orchestrator across repl lines.
- Router quality on light profile: llama3.2:3b intent classification runs ~78%
  on the 9-item `utterances_route.json` fixture (opt-in test threshold lowered
  0.8→0.7). Improve `prompts/route.txt` (few-shot examples, tighter definitions),
  grow the fixture, and/or route on `quality`/cloud even in hybrid. This matters
  for hybrid users (routing stays local).
- Spec §4.5: `persist_store`/resolver never merge an extraction's `aliases` /
  new `notes` into an already-matched entity row (aliases are write-once at
  creation). Implement alias/notes enrichment on resolve-hit.
- ~~`Config` should validate `embedding_dim == db.models.EMBED_DIM`~~ — DONE
  2026-09-08 (load_config raises ConfigError on mismatch).
- Gate UX (spec §4.3): replying "no" to a confirmation gate currently gets
  routed+stored as a fresh utterance; gate message should also carry a one-line
  "about to store: …" summary (the `_summarize` builder already exists).
- ~~`Orchestrator.handle` never closes the session~~ — DONE 2026-09-08
  (handle() owns one session per call: commit on normal/gated, rollback+raise
  on unexpected, close in finally).
- ~~`EntityResolver.resolve` full-scans the entity table~~ — DONE 2026-09-08
  (`_candidate_rows` narrows to exact/overlap ∪ trigram, capped at 50; needs
  the pg_trgm indexes from migration 0002). Alias trigram match is still an
  expression filter (array_to_string), not index-backed — revisit if entity
  counts get large.
- Occasion dedupe is global by lowercased name (two people's "birthday" collapse;
  a later better `date_phrase` never updates the row).
- ~~Committing integration test that the utterance survives a `PersistError`~~
  — DONE 2026-09-08 (`test_handle_commits_utterance_even_when_write_fails`:
  a second session on the same connection sees the committed utterance, no
  record).
- Declare the b-tree/GIN/HNSW/trgm indexes on the ORM models (currently only in
  the migrations) so `alembic check` / autogenerate is clean and can gate CI.
  Partial: `aliases` now has `server_default` on the ORM (2026-09-08); the
  index set is still migration-only. conftest builds the test schema via
  `alembic upgrade head`, so column/type/nullability drift is caught, not
  indexes.
- ~~Plan 2: query pipeline~~ — DONE 2026-09-08 (see completed.md).
- Plan 2 follow-up: `aggregation` (count/latest) parsed onto SubQuery but not
  compiled into SQL — `func.count()` / `ORDER BY recency LIMIT 1` branch in
  `compile_structured()`.
- ~~Plan 3: FastAPI service + pywebview desktop app~~ — DONE 2026-09-08
  (see completed.md).
- Plan 3 follow-ups: token streaming over `/ws`; real Mermaid rendering (needs a
  deliberately-vendored lib); run `orchestrator.handle` off the event-loop
  thread; `GET /utterances` history endpoint; `io run` window not yet exercised
  on a real display.
- ~~Plan 4: voice~~ — DONE 2026-09-08 (see completed.md). Spec §6.1 added.
- Plan 4 follow-ups: the real Whisper/Piper adapters + mic/hotkey/playback seams
  need a machine with audio + the models to verify end-to-end (`io listen` full
  loop, transcription accuracy, hotkey capture, playback) — run
  `IO_VOICE_TESTS=1 uv run pytest -m voice` and `uv run io listen` there. Also:
  download the default Piper voice; token-streamed TTS (needs `/ws` streaming);
  wake-word; barge-in; input/output device selection in config; true
  hold-to-talk (pynput GlobalHotKeys is toggle-only — current impl is
  press-to-start / press-to-stop).
