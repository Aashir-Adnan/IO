# Backlog (highest priority on top)

- **Tasks & Collections follow-ups** (feature implemented 2026-09-10/11,
  branch `io-window-glass`, 501 pass — see `.claude/knowledge/
  tasks-and-collections.md` and the full ledger `.superpowers/sdd/
  2026-09-10-tasks-and-collections/progress.md` for every reviewer finding).
  Consolidated from the ledger's scattered "Deferred backlog" sections:
  - **Completion-verb vocabulary gap** — "I watched X" / "I read X" /
    "finished watching/reading X" don't close a watchlist/reading-list item;
    `_DONE_VERB` (orchestrator.py) has no watch/read synonyms, so these fall
    through to store as a duplicate note instead of a close.
  - **`_try_complete`'s `none` branch is lossy** — "I finished the marathon"
    with no matching open task stores nothing (the verbatim utterance
    survives with `marker="complete"`, but no record). Fix: fall through to
    the planner on `none`, reusing the flushed utterance.
  - **`complete_record` can't express "dropped" via the model** — the
    capability route always defaults `target_status="done"`; only the regex
    precheck (`_COMPLETE_DROP`) can drop. Add a `status` arg constrained to
    `{done,dropped}`, validated in Python.
  - **Real latent bug (D-park-5, not yet fixed)**: `set_record_status`
    (`io_assistant/tasks/complete.py`) clears `completed_at` only when
    `status == "open"`, not `"dropped"` — a done→dropped transition (e.g. via
    `PATCH /record`) leaves a stale `completed_at` on a dropped row. Not
    reachable from the Task 8 checkbox UI today. One-line fix.
  - `_DEFINITE` false negatives (orchestrator.py) — "I finished writing the
    report" (gerund), "I finished dinner"/"laundry" (bare noun), "the report
    is done" (copular form not covered), "did the dishes" (eaten by
    `_COMPLETE_QUESTION`). Each files a duplicate open task on the default
    (split) config; not a regression.
  - `count == 0` phrases via `force=True` as "(there are 0 matching items)"
    instead of the deterministic `_EMPTY` string — probably fine, untested.
  - Smaller regex/cosmetic items, not yet worth a dedicated task: `_COMPLETE_TAIL`
    can clip a hyphenated title ("the write-off" → "the write-"); apostrophe-less
    contractions ("ive finished the report") miss `_I_PREFIX`; dead `if done is
    not None` guard in `_handle_in_session`; `CloseOutcome` not frozen;
    `resolve_collection` missing a `-> Collection | None` return annotation;
    `extract/schema.py` `item_noun` hint says `str`, should say `str | null`;
    redundant unique constraint on `collections.kind_slug` (ORM + named index,
    inert); no index on `records.completed_at` (add if a query ever
    filters/sorts by it); `_due_label` has no "in N days" branch (days 2-6
    render as a bare weekday); `respond.py`'s overdue check compares raw
    `due < now` vs `rank.py`'s tz-safe `_as_dt` (works today, inconsistent);
    redundant function-local `import datetime as _dt` (service/app.py,
    twice in `record_edit`); `FakeBackend.last_context` is a single shared
    field (a `last_contexts` list would let tests assert both context halves);
    `render_context` wraps the known-list vocabulary as "Recent conversation:"
    (honest framing would be a dedicated prompt slot); no `plan.txt` rule for
    WHEN to use `aggregation: "count"`; `compile_count` wants a one-line
    comment noting it deliberately has no `_LIMIT`; records-browser collection
    chips have no empty-state guard ("no collections yet" vs "still loading");
    `tests/test_cli.py` has no autouse DB-wipe fixture (works today, single
    file).
  - Not yet re-verified live against the running desktop app this session
    (the plan's Phase 5 checkpoint) — `.\dev.ps1 up` then: "I need to X" →
    due today; check it off in the tasklist card; "add X to my movies to
    watch" then "what's on my watchlist".

- **Web-backed answers** (Phases 1–5 done 2026-09-09, branch `io-window-glass`,
  spec `2026-09-09-web-answers-design.md`, knowledge `web-answers.md`).
  Follow-ups:
  - **Run it live** — `[web].enabled = true`, `dev.ps1 up` (starts SearXNG),
    try "what's the news on Korea", "USD to PKR", "track the bitcoin price",
    "USD to PKR vs yesterday". First real SearXNG contact — the `settings.yml`
    JSON-format + engine list may need tuning.
  - `query/compile.py` — actually compile the parsed `aggregation` (`latest`)
    so Tier B deltas go through the general query pipeline, not just
    `poller.delta_reading`. (`count` is compiled — Tasks & Collections Group H.)
  - A `regex`-type catalogue entry (petrol PKR needs a stable source page).
  - Cloud search provider slot (`[web].provider` beyond `searxng`/`none`).
  - `io web` / `io track` CLI; a `[web]` toggle in frontend settings.
  - Re-run the decide eval with `[web].enabled` to check the `decide.txt`
    exception line doesn't regress Haiku.

- **Phase 2 — Files & Media** (specs written 2026-09-08):
  - ~~Spec A — file index + text exploration~~ — DONE 2026-09-08 on branch
    `io-phase-2a-file-index` (267 pass). Not merged. See completed.md.
    Follow-ups (spec §13): agentic exploration loop; `query`↔`file`
    cross-fallback in one turn; filesystem watching vs lazy hash checks;
    learned co-retrieval edges; OCR for scanned PDFs; opt-in `-m ollama`
    `file`-class router accuracy re-baseline.
  - ~~Spec C — media library & captioning~~ — DONE 2026-09-08 on branch
    `io-phase-2c-media` (292 pass). Not merged. See completed.md. Follow-ups:
    ffmpeg video-frame thumbnails; HEIC via `pillow-heif`; EXIF GPS → `Place`.
  - ~~Spec B — desktop packaging~~ — DONE 2026-09-08 on branch
    `io-phase-2b-packaging` (298 pass; build verified locally). See completed.md.
    Follow-ups: run a full clean-env runtime check on Windows (`dev.ps1 up`
    first — the frozen app does NOT migrate; then double-click `dist\IO\IO.exe`,
    launch twice); a blocking "DB unreachable" dialog; bundling voice deps or a
    separate voice add-on; macOS/Linux packaging; code signing; auto-update.

- ~~Plan 6: Nocturne desktop client~~ — DONE 2026-09-08 (see completed.md).
  Phase 1.5 complete.
- Phase 1.5 deferred: state 1d task runner (agent loop + approval gates + live
  log + telemetry); external-source provenance (Calendar/Messages); entity-file
  browser (Timeline/Sources/Review still stubs); real `/ws` token streaming;
  Kokoro `Speaker` adapter (`[voice].provider`).
- Plan 6 follow-ups: run the Playwright DOM smoke on a machine with chromium
  (`uv run playwright install chromium`; `IO_UI_TESTS=1 uv run pytest -m ui`);
  exercise the pywebview window + native menu + geometry persistence on a real
  display; real Mermaid rendering (vendored lib); the `talk`/Listening view mic
  path needs a real mic to verify.

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
- ~~Date grounding vs absolute/ISO dates~~ — DONE 2026-09-09. `ground()` has a
  `dateutil.parser` fuzzy fallback (`_parse_absolute` in `resolve/dates.py`):
  "the 10th of september", "tomorrow, the 10th of september", "sept 10",
  ISO "2026-09-10" all ground; a bare past month/day rolls to next year; true
  garbage still gates. `tests/test_dates.py` +5. (2026-09-10 fix: the
  "learned nothing" guard was rejecting a phrase that grounded to exactly
  today-at-noon — now also checks for a digit/month token first.)

- **Unified `decide` pipeline** — Phases 1–5 DONE 2026-09-09. Combined mode
  live on anthropic (`[backend].decide = "auto"`), 17/17 on the Haiku eval.
  Tokenised `file_tags` power "fetch pictures of me and nafay". **Remaining:**
  - Measure the actual token saving; enable combined on local `quality` +
    re-baseline against `llama3.2` on that profile.
  - `PendingStore` only holds the gated store — a multi-step turn where the
    store gates loses the other steps (`_merge_results` drops them).
  - `file_tags` backfill: existing captions/summaries only get tags on the
    next re-index or caption edit. A one-shot backfill would tag the corpus now.
  - "me" expansion in `show_photos` args: when `decide` returns `of:["Nafay"]`
    only, the photo of me+Nafay still matches, but a photo of just-me wouldn't.
    Consider always injecting the self terms.
- **Tauri shell migration** — spec `2026-09-09-tauri-shell-migration-
  design.md`. Replace pywebview with a Rust Tauri host (Python service as a
  sidecar), keep the web frontend as-is. 5 phases, each shippable.

- **Media-by-entity gallery query** — "fetch all pictures of me and nafay".
  The caption→`FileEntityLink`→embed half works (`apply_caption`,
  `search.py` joins `FileEntityLink`), but the retrieval comes back as a
  **text `files` card**, not a photo gallery, and isn't media-filtered. Want:
  route "pictures/photos/videos of <people>" → a `GalleryCard` filtered to
  media linked to those entities. Fits the `decide` spec's `show_photos`
  action. ("me" also isn't a Person row — no self entity.)
- **Local streaming Whisper — end-to-end unverified**. Plumbing + WS + config
  tested; needs a real mic + the `large-v3-turbo` download to confirm the
  rolling-transcribe UX. Partial-stabilisation params (`_MIN_NEW_SECONDS`,
  `_KEEP_PROVISIONAL_SECONDS`) will likely need tuning against real speech.
- **Record edit is title/date/kind/domain/status only** — no body edit, no
  entity-link edit (add/remove a person from a record), no undo. Entity
  delete has no "merge into" (for dedup — two "birthday" occasions).
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


## Requested 2026-09-21 (not yet specced)

- **C — Home-screen widget board**: user-placeable, premade widgets (weather,
  time zones, to-do, important emails/notifications). Open: weather source
  (needs a new sanctioned outbound call), email/notification source, layout
  model (grid vs free placement).
- **B — Small pending-tasks window**: second pywebview window. Open:
  always-on-top vs normal, refresh source (reuse C's to-do widget).
- **E — Phone app**: native cross-platform rewrite (Flutter vs React Native
  undecided), standalone, depends on A (API-key-only) and F (sync). Prompts and
  `decide_cases.json` are the shared conformance contract with the Python core.
  Open: on-device embedder, local store, API-key storage on device (amends
  "credential never stored by IO").
