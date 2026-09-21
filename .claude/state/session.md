# Current session

## 2026-09-21 — status UI shipped; A / D / F specs written (branch `io-window-glass`)

- **S — Claude-style live status: DONE, uncommitted.** `frontend/progress.js`
  (`thoughtLabel`, TDD: `tests/test_frontend_progress.py`), `conversation.js`
  (collapsible `.turn-pending`, stage cross-fade, collapses to "Thought for Ns"
  `<details>`), `app.css` (pulse glyph, `.shimmer`, reduced-motion fallback,
  composer overlay shares it). Verified in the browser pane with a stubbed
  `api.sendText`; Docker was down so the full stack/suite was not run.
- **A — Ollama-optional: DONE** (committed; see completed.md). Plan
  `docs/superpowers/plans/2026-09-21-ollama-optional.md`. **D — self-update: DONE**
  (see completed.md). Spec F approved, plan not yet written — next: F.
- **Specs (approved):**
  `docs/superpowers/specs/2026-09-21-ollama-optional-design.md` (A),
  `…-self-update-design.md` (D), `…-memory-sync-design.md` (F, Supabase,
  server-readable, memories+affiliations+tasks+chat).
- **Not started** (open questions in backlog): C widget board, B pending-tasks
  window, E native phone app (Flutter/RN; needs A + F first).
- Next: user reviews specs → `writing-plans` per spec. Suggested order
  A → D → F → C/B → E.

---

**"IO Glass" reskin** — on branch **`io-window-glass`** (from the acrylic
commit `346aa3c`; NOT merged). Replaced the dark Nocturne shell wholesale with
the light pearl-glass look from `docs/design/IO Glass.dc.html` (imported from
the "IO UI Mockups" Claude Design project). No theme toggle.
- `tokens.css` — pearl-glass palette (`--pearl*`, `--ink*`, `--hair`,
  `--glass`, `--ground #c9c6d4`); accent ramp kept; same 5 woff2.
- `app.css` — full restyle. `.win` is one frosted card; new `#topbar`
  (dots + `IO` + `#status` + gear) replaces `.winctl`/floating `.gear`.
- `index.html` — topbar markup; `#drawer` removed.
- `app.js` — `VIEWS` gains `library` (`gallery`/`files` alias to it); drawer
  wiring + `toggleHistory` gone; `route()` clears `#status`.
- `views/standby.js` — single-line `HH:MM` clock + agenda rows (was stacked
  clock + `.chip` pills); ask-bar pill with folder/history shortcuts.
- `views/conversation.js` + new `components/history.js` — persistent 268px
  history rail (was slide-over `drawer.js`, now deleted); record cards render
  as inline entity pills.
- new `views/library.js` — merges `files.js` + `gallery.js` into the 3-pane
  folders/grid/inspector view; exports `mountFolders` for the settings sheet.
  `files.js`, `gallery.js`, `components/drawer.js` deleted.
- `vendor/icons.js` — +6 vendored Phosphor paths (house, images,
  magnifyingGlass, clockCounterClockwise, squaresFour, list) + caret aliases.
- `tests/test_frontend_smoke.py` — `.chip`→`.agenda-row` assertion.
- Green: `test_frontend_assets` + `_markdown` + `_typing` (7 pass); `node
  --check` on all 18 JS files. Playwright smoke still skips (not installed).
  **Not yet run live** — needs the Docker+Ollama stack.

**Follow-up round (user feedback):**
1. `Alt+Enter` → toggle fullscreen (global, `app.js`). `⌥Space` stays voice-only.
2. Standby mic now shows real feedback: `.recording` state — orb `listening`
   + live level meter, ask bar → `.askbar-live` (waveform + `Listening…` +
   elapsed), then `Transcribing…`. Whisper is batch so no live words.
3a. Rotating placeholder — `EXAMPLES[]` (feature-spanning prompts) cycled
    through the ask-bar placeholder, freezes on typing.
- Polish from the live pass: body ground → diagonal lavender gradient;
  `.win` → `position:fixed;inset:0` (was `100vh`, left a gap headless);
  `⌥` glyph → `Alt` (not in the Inter subset, and Windows anyway);
  conversation empty-thread hint + `onPick` re-hydrate when a chat is picked
  from the rail while already in the view; `.settings` more opaque so the
  topbar doesn't ghost through.

**Verified live** (2026-09-09) — `.\dev.ps1 up`, driven headless via Chrome
CDP. Standby / conversation (history load + a real query turn, markdown,
entity pills) / library 3-pane / settings sheet all render correctly against
the real backend. Screenshots in the session scratchpad.

**Round 3 (user feedback):**
1. **Transcription 404** — `/files/transcribe` was mounted only under
   `if config.files.enabled` in `service/app.py`; the ask-bar mic hit it and
   silently 404'd. Split it out as **`POST /voice/transcribe`** (always
   mounted); `api.js` updated; new test
   `test_voice_transcribe_only_available_without_files_feature`. Still batch
   (transcribes on release, no live words).
2. **Folder add failed** — `[files] enabled = false` in `config.toml` → the
   whole `/files*` block unmounted. Set `enabled = true` +
   `allowlist_roots = ["~/Documents","~/Downloads","~/Desktop","~/Pictures"]`.
   `api.js` `j()` now surfaces the server `detail`; library shows the real
   error. Verified: registering `~/Downloads` → 1304 discovered, `/files/open`
   → 55 media. ⚠ files-on + `provider="anthropic"` sends file text to Anthropic.
3. **Theme system** — `tokens.css` now two palettes behind one variable set.
   **Dark is the default** (Nocturne restored — `#1b1d2b` panels, `#12131b`
   glow ground, `--glass:none`); `data-theme="light"` = the pearl look.
   app.css colours all route through tokens (`--sheen/--fill/--wash/--scrim`
   /…). `index.html` inline script applies `localStorage["io.theme"]` pre-paint;
   Settings → Appearance toggles. Both themes verified across all views.

Pre-existing failure (not mine): `test_service_standby.py::test_standby_panel`
fails on a clean `346aa3c` checkout too — `io_test` chip data pollution.

**Round 4 (user feedback):**
1. **Live transcription — Soniox** (user chose "key server-side"). New:
   `rules/local-first.md` amended (sanctioned cloud path #2 — `soniox.com`,
   gated on `voice.stt_provider="soniox"` + `SONIOX_API_KEY`).
   `io_assistant/transcribe/soniox.py:mint_temp_key`. Service:
   `GET /voice/stt`, `POST /voice/stream-token`. Frontend:
   `vendor/soniox.js:SonioxStream` (streams 16 kHz PCM16 to
   `wss://stt-rt.soniox.com`, interim + final) + `mic.js:createMic` (unified;
   Soniox when `store.sttStreaming`, else Whisper batch; any failure falls
   back). `config.toml` `stt_provider = "soniox"` (harmless without the key).
   Standby ask bar shows the live interim transcript (`.askbar-live-label`
   clips left-first). **Not verified end-to-end — needs `SONIOX_API_KEY`.**
   503/config/fallback paths tested + verified live.
2. **Fullscreen can't be dragged** — `runner.py` `easy_drag=False`;
   `toggle_fullscreen()`/`is_fullscreen()` return the bool; `app.js` mirrors to
   `<html data-fullscreen>`; CSS kills the topbar drag region + squares the
   frame. `Alt+Enter` uses the same path.
3. **Window buttons prominent** — `.topbar-dot` dots → `.winctl` /
   `.winctl-btn`: three real icon buttons (minus / cornersOut↔cornersIn / x),
   26px, bordered, hover states. `cornersIn` icon vendored.
4. **"not under a registered path"** — `FileIndex.register` no longer enforces
   the allowlist (explicit registration = authorization; still rejects
   nonexistent / symlink-escape / excluded). `api.js` `j()` surfaces the
   server `detail`; library shows the real error. `test_register_denied_path`
   → `test_register_rejects_nonexistent_path` + `test_register_outside_
   allowlist_is_allowed`.
5. **Clock** (mid-turn) — two-row `HH`/`MM`, enlarged
   (`clamp(72px,13vw,148px)`); weekday + month-day stacked in a column to its
   right (`.standby-clockrow` / `.clk-when`).

Full suite: **306 pass / 10 skip** (+ the 1 pre-existing standby fail).

**Round 5 (user feedback):**
- **Window never draggable** — topbar drag region removed entirely.
- **Apple-adjacent restyle** — killed all button/input/card borders & outlines;
  soft filled surfaces, soft focus rings (box-shadow, never `outline`);
  iOS-style segmented `.theme-toggle`; `.winctl-btn` are filled pills.
- **Library scroll** — `.lib-col { min-height: 0 }` (flex chain wasn't
  constraining the grid).
- **Square thumbnails** — `.lib-tile-thumb` / `.lib-insp-preview`
  `aspect-ratio: 1`, media `object-fit: contain` (letterboxed), non-media a
  centred glyph.
- **Lightbox** — `components/lightbox.js`; double-click an image/video tile or
  click the inspector preview → full-screen viewer (Esc / backdrop / ✕).
- **View transitions** — `route()` fades `#view` out (120 ms) then staggers
  the new view in big→small via `#view.entering` tiers. Cross-view sends now
  route through `ctx._pending` (deferred mount would've lost `#thread`).
- **All file types in the library** — `walk_dir(include_all=True)`;
  `gallery.open_folder` lists every file (`media_kind` `doc`/`file`,
  `indexed=false`, `size_bytes`); `GalleryItem` gained `size_bytes` + `indexed`.
  Grid caps at 400 + "+N more".
- **Soniox is LIVE** — `SONIOX_API_KEY` in `.env`; `/voice/stt` →
  `{provider:"soniox",streaming:true}`, `/voice/stream-token` mints a real temp
  token from `api.soniox.com`. Browser WS streaming not verifiable headless
  (no mic) but the full token round-trip works.

Full suite: **307 pass / 10 skip** (+ the 1 pre-existing standby fail).

**Round 7 (user feedback):**
- **Folder scroll fixed for real** — `#view { min-height: 0 }` was missing, so
  every flex view grew to fit content instead of scrolling. One line.
- **Memory browser** — `views/records.js` + topbar brain icon. `GET /records`,
  `PATCH /record/{id}` (title re-embeds, `when_phrase` re-grounds),
  `DELETE /record/{id}`, `DELETE /entity/{etype}/{id}`. Editable title, date,
  inline delete (2-tap), domain filters. +`test_records_browse_edit_delete`.
- **Library**: grid⇄list toggle + size stepper in the breadcrumb (persisted);
  per-folder hover **× forget** in the nav; "Back to chat" → a prominent filled
  icon at the top of the nav.
- **Text file viewer** — double-click a `.md/.js/.ts/…` tile → `Lightbox`
  renders `/files/content` text in a `<pre>` panel. `lightbox.js` now takes
  `{text,name}` too.
- **Input focus ring** removed everywhere (round 6 carried); the dark ground
  reworked.
- Build-on-message-end hook: user said "never mind ignore" — dropped.

Full suite: **315 pass / 10 skip** (+ the 1 pre-existing standby fail).

**Round 8 — "start working on the backlog and spec as implementation":**
Implemented the **unified `decide` pipeline** (spec, Phases 1–3):
- `io_assistant/models_domain.py` — `Step` / `Plan`.
- `io_assistant/actions/` — `Capability` + `REGISTRY` (`open_folder`,
  `show_photos`, `search_files`) + `describe_capabilities` / `validate_action`.
- `io_assistant/decide/` — `DecidePlanner` (split | combined, mode from
  `[backend].decide`), `parse.py:parse_plan` (tolerant JSON→Plan).
- `prompts/decide.txt` — the combined prompt.
- `AnthropicBackend.decide` — one cached call → `Plan`.
- `Orchestrator` — `_dispatch_step` loop + `_merge_results` (multi-step:
  gate wins, else concat + merge cards) + `_run_action` handlers.
- `config.toml` `[backend] decide = "auto"` — **combined is live for this
  user** (provider=anthropic). Any failure → split fallback.
- **Verified live**: "remind me to submit the report tomorrow, and what tasks
  do I have?" → one turn that stores AND answers. "guess who I ran into at
  work today" now routes to query (was unknown).
- Tests: `test_decide_planner.py` (6), `test_decide_parse.py` (8),
  `test_decide_combined.py` (4). Full suite unchanged elsewhere.

Full suite: **333 pass / 10 skip** (+ the 1 pre-existing standby fail).

**Round 9 — decide Phases 4 & 5 + tokenised caption tags:**
- **`file_tags`** (migration 0006, `io_assistant/files/tags.py`) — a caption
  "me and nafay in hunza" → tags (Nafay/person, Hunza/place, Me/self,
  <owner>/self), media_kind denormalised. Written by `apply_caption` (w/
  entity ids) + `FileIndexer` (from summaries). `config.owner_name` resolves
  "me"/"I"/"my".
- **`media_query.py`** — `media_nodes_for_terms` ranks media by tag coverage
  (exact + pg_trgm fuzzy). `gallery.gallery_from_nodes` builds a folder-less
  `GalleryCard`.
- **Phase 4** — `_action_show_photos` → real gallery; `_file_turn` routes
  "photos/pictures/videos of X"; `search.py` tag bump. **Verified live**:
  caption a jpg → "fetch all pictures of me and Nafay" → gallery card.
- **Phase 5** — `tests/fixtures/decide_cases.json` +
  `tests/test_decide_eval.py` (opt-in). **17/17 on Haiku** after tightening
  `decide.txt`'s `file` bullet.
- Tests: `test_media_query.py` (7), `test_files_caption.py` +1,
  `test_orchestrator_files.py` +1, `test_decide_eval.py` (opt-in).

Full suite: **339 pass / 11 skip** (+ the 1 pre-existing standby fail).

**Round 9b — tags cover possessions/documents too:**
- `salient_terms` items → `thing` tags (was already there); `media_query`
  matching gained **whole-word containment** (`"cnic"` matches tag
  `"cnic card"` via POSIX `\y` regex) alongside exact + trgm.
- `_STOP` gained generic doc suffixes (`card`, `scan`, `copy`, `document`) —
  noise as a standalone query term, kept inside a tag phrase.
- `_file_turn` regex broadened: "pull up / show me / where's … my <X>" also
  tries the gallery.
- `show_photos` registry summary + decide_cases fixtures mention documents.
- **Verified live**: caption "scan of my passport and CNIC card" (linked as
  *items*) → "pull up my passport" and "where is my CNIC" both return a
  gallery card.
- Decide eval: **18/19 on Haiku** ("where's my CNIC card?" is genuinely
  ambiguous — fixture now accepts query too).

Full suite: **341 pass / 11 skip** (+ the 1 pre-existing standby fail).
Verified live in both themes — screenshots in the scratchpad.

**Round 6 (user feedback):**
- **Local streaming Whisper** — `voice.stt_provider = "whisper-stream"`
  (now the config default). `transcribe/streaming.py:StreamingWhisper` +
  `WS /ws/transcribe` (rolling tail re-transcribe, commit >2 s old, keep last
  2 s provisional). Frontend `vendor/localstream.js:LocalStream` +
  `vendor/pcm.js`; `mic.js` picks whisper-stream / soniox / batch off
  `store.sttProvider`. First mic use downloads `large-v3-turbo` (~1.5 GB, GPU).
  `/voice/stt` verified → `{provider:"whisper-stream",streaming:true}`; WS
  tested with a stub. **Not exercised end-to-end** (needs mic + the download).
- **Date grounding fixed** — `resolve/dates.py` `_parse_absolute` (dateutil
  fuzzy fallback). "tomorrow, the 10th of september" → 2026-09-10. +5 tests.
- **Input focus ring removed** — `.askbar`/`.composer`/`.lib-ask` just shift
  fill on `:focus-within`; text fields never get the `:focus-visible` glow.
- **Background reworked** — richer dark `--win-bg` (layered radials +
  linear), deeper `--ground`; light `--body-bg` gets a soft highlight.
- **Window still-draggable** = the running window is stale; `easy_drag=False`
  + no drag region is confirmed in code (pywebview 6.2.1 source). Relaunch
  `dev.ps1 up -Window`, or `dev.ps1 build` for the exe. Added a `user-select`
  backstop.
- **Two specs written** (need review, not scheduled):
  `docs/superpowers/specs/2026-09-09-tauri-shell-migration-design.md` and
  `…-unified-decide-pipeline-design.md`.

Full suite: **314 pass / 10 skip** (+ the 1 pre-existing standby fail).
3b. **Deferred** — "feel like a chatbot" / conversational query generation
    ("guess who I met at work today?" → auto-query work + affiliated people)
    is a route/plan/respond prompt rewrite + eval fixtures. Needs its own
    brainstorm/design. See route.txt / plan.txt / respond.txt and
    `.claude/knowledge/query-pipeline.md`.

---

**Phase 2 (files 2A + media 2C + packaging 2B) merged to `main`** and pushed
(`origin/main` = `41aaaa9`).

**Phase 2B.1 (full-featured bundle) + UI shell polish** — on branch
**`io-ui-minimal`** (from `io-phase-2b1-full-bundle` off `main`; NOT
merged). Full suite **302 pass / 10 skip**.

### 2B.1 — full bundle
- `packaging/io.spec` bundles **voice** (`collect_all` piper/faster_whisper/
  sounddevice/ctranslate2/onnxruntime/av; `packaging/hooks/hook-webrtcvad.py`
  overrides the broken contrib hook; `torch` excluded). Voice **models** still
  download on first use — `VoiceModels._ensure_voice_model` fetches the Piper
  `.onnx` on first `/voice` synth.
- `io_assistant/service/bootstrap.py` — `ensure_database(config)`: ping DB →
  `docker compose -p io -f <bundle>/docker-compose.yml up -d db` if down → wait →
  `alembic upgrade head`. `cli.run()`/`serve()` call it; `runner.error_dialog`
  shows `BootstrapError` in a pywebview window. Bundle ships `docker-compose.yml`
  + `scripts/initdb/`. **Prereq: Docker Desktop running.**
- **Verified locally**: `dist/IO/IO.exe` (~25 MB / ~350 MB) starts its own DB
  container, migrates, serves `/health`+`/voice/health`+`/standby`; 2nd launch
  → browser + exit (single-instance).

### UI — minimal shell
- Removed the white titlebar; `#status` → bottom of rail.
- Collapsible rail (216↔66 px, `localStorage["io.rail.collapsed"]`), icon+label,
  `IO` wordmark, chevron toggle.
- Standby: big centred iPhone-style clock + long date, then greeting/orb/stats/
  chips/composer, centre-aligned.
- **Orb fixed** — `orb.js` mounts its own fixed-size `.orb` div inside the host
  (was restyling the host → ellipse); layers centre via `inset:0;margin:auto`.
- `[hidden]{display:none!important}` (the drawer was still 240 px wide when hidden).
- Native folder picker: `runner.open_window` `js_api.pick_folder()` →
  `window.create_file_dialog(FOLDER_DIALOG)`; Files view "Choose folder…" button.
- Static assets served `Cache-Control: no-store` (`_NoCacheStatic`).

**Next:**
1. Final rebuild (`dev.ps1 build`) + `dev.ps1 install` → Desktop shortcut; a
   real fullscreen runtime check.
2. Merge `io-ui-minimal` → `main`.
3. Open-source readiness (on hold): default `provider = "local"`, verify local
   backend end-to-end, LICENSE, README, CI, make repo public.

Tests: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test'
uv run pytest -q -p no:warnings`.

---

## Web-backed answers (2026-09-09, branch `io-window-glass`)

Opt-in 3-tier web answers — spec `docs/superpowers/specs/2026-09-09-web-answers-design.md`,
knowledge `.claude/knowledge/web-answers.md`. **Phases 1–4 done, tested (393
pass / 11 skip). Phase 5 = docs done; eval fixtures light (precheck covered by
`test_orchestrator_web` parametrize).**

- **1** — `WebConfig` (`config.py`) + commented `[web]` in `config.toml`;
  `rules/local-first.md` cases 3–5; migration `0007_web.py` (`web_cache` +
  `trackers`) + `WebCache`/`Tracker` models; `docker-compose.yml` `searxng`
  service + `scripts/searxng/settings.yml` (JSON output on); `dev.ps1`
  `Test-WebEnabled` gate (SearXNG only starts when `[web].enabled`).
- **2** — `io_assistant/web/{search,fetch,answer}.py`. `WebAnswerer.answer`:
  cache → Tier A (Python template of a SearXNG instant answer) → Tier C
  (`fetch_and_extract` top pages → `backend.answer_from_files`, 1 cached call).
  `GET /web?q=&kind=` smoke endpoint (404 when off).
- **3** — `web` capability (`requires_web`), `describe_capabilities(web_enabled=)`,
  `decide.txt` exception line. `Orchestrator._web_precheck` (regex + first
  -person guard → news/fact/track/None), `_run_web`, `_action_web`.
  `WebCard`/`WebSource` + `card.js` `web` branch + `globe` icon.
  `_run_action` now degrades an unhandled slug to a query.
- **4** — `web/{trackers,poller}.py`. `CATALOGUE` (usd-pkr, gbp-pkr, bitcoin,
  gold), `match_catalogue`, regex/instant `extract_reading` (no model).
  `register_tracker`/`poll_tracker`/`poll_due` write `reading` Records;
  `latest_readings` + `delta_reading` (pure Python today-vs-prior-day).
  `TrackerPoller` daemon thread started in `create_app` when `[web].enabled`.
  `track` capability + `_action_track` + `_tracker_answer` (Tier B first in
  `_run_web`).

**Not done:** cloud search providers; a `regex` catalogue entry (petrol needs a
known page); `io web`/`io track` CLI; `[web]` frontend settings toggle;
`query/compile.py` still ignores the parsed `aggregation` field. **Not run live
against a real SearXNG container yet.** decide eval not re-run (`decide.txt`
change is guarded by "if a web capability is listed" and web is off in the eval
config).

---

## "Fix this with everything" (2026-09-10, branch `io-window-glass`)

Four workstreams from one request, all implemented + tested (404 pass / 11 skip
at completion, with the DB + Ollama stack up):

1. **Family-query bug — `rows_to_json` serializer holes.** "Who is my family"
   failed because Person rows serialised with `title: null` (`rows_to_json`
   looked for `.name`; `Person` has `.canonical_name`) and `Record.body` was
   never handed to the phrasing model. Fix in `io_assistant/query/respond.py`:
   `_name_of(obj)` (`title` → `name` → `canonical_name`), each row now carries
   `detail` (body), `notes`, `attributes`. `prompts/plan.txt` — "who is my
   <group>" routes to `target_type "record"` (semantic), not `person`. Regr.
   tests in `test_query_respond.py` + `test_query_pipeline.py`;
   `conftest.FakeBackend.phrase` records `last_phrase_rows`.
2. **Desktop-only (no browser).** "Remove affordances only" — no hard block on
   `/app/`. `service/runner.py` `raise_window()` (module `_WINDOW` ref;
   `restore()` + Win32 `ShowWindow`/`SetForegroundWindow`). `POST /window/raise`
   endpoint. `singleton.surface_running_instance` POSTs it (200 → "brought to
   front", 404 → headless hint) — no more `webbrowser`. `dev.ps1`: `up` opens
   the window by default, new `serve` (= `up -NoWindow`) for headless; `app`
   command opens the window too. CLAUDE.md / run-local.md / tests updated.
3. **Fast folder open.** `files/gallery.open_folder` rewritten — one
   `walk_dir(include_all=True)` + one batched `FileNode` lookup + one
   `_entities_for_many`, thumbnails via generate-on-miss (`/files/thumb` now
   persists `thumb_path`), unindexed media deferred to `index_queue.enqueue_many`
   (the existing `IndexQueue` daemon) instead of indexing on the request thread.
   Frontend `library.js` `watchIndexing()` polls + auto-refreshes the grid,
   crumb shows "indexing N…". `orchestrator._index_queue` wired.
4. **Processing cue.** `io_assistant/progress.py` — contextvar channel
   (`progress_to(cb)` / `emit(stage, detail)`), zero signature churn in the deep
   pipeline; `asyncio.to_thread` copies the context. `_emit` calls in
   orchestrator / query pipeline / web answer. `/ws` streams `{type:"progress"}`
   frames via a threadsafe queue. Frontend: live `.turn-pending` strip in the
   thread that collapses to a `<details class="turn-steps">` on the answer.
   `test_progress.py` + `test_service_ws.py` updated.

**UI round (2026-09-10, same branch):**
- **Home-screen ask bar wraps** — `views/standby.js` `<input>` → auto-growing
  `<textarea>` (Enter sends, Shift+Enter newline, grows to 132px). `.askbar`
  `min-height` + `padding` for the growing field; `.askbar.busy` flash
  ("Working…") on submit before the view swaps.
- **"or hold Alt Space" hint removed** — `.askbar-kbd` span + CSS gone;
  `composer.js` default placeholder → "Ask IO anything". Alt+Space still toggles
  voice (`app.js` / `standby.js` keydown unchanged).
- **Processing text on the input** — `components/composer.js` gains
  `{setBusy, setStatus}` + a `.composer-status` overlay (spinner + live stage).
  `conversation.js` drives it from the same `/ws` progress frames as the thread
  strip; cleared on answer / error.
- Removed a duplicate `@keyframes io-spin` in `app.css`.
- Verified live headless (Chrome CDP, `/app/`): Alt-Space hint gone, a long
  message wraps to 4 lines in the ask bar, the composer shows
  "⟳ Planning your request" during the turn and clears on the answer.
  Screenshots in the session scratchpad.

**Date-grounding fix (found while triaging the suite):**
`resolve/dates._parse_absolute` rejected any phrase that grounded to *exactly*
today-at-noon (`dt == base` "learned nothing" guard) — so on 2026-09-10,
`ground("the 10th of september")` returned `ok=False` and `PATCH /record` 422'd
(`test_records_browse_edit_delete`). Guard now also requires the phrase to carry
no date-ish token (`_DATEISH` = a digit or month name) before bailing.
+`test_absolute_date_equal_to_today_still_grounds`.

**Suite: 405 pass / 11 skip / 1 deselected** (DB + Ollama up).
`test_service_standby.py::test_standby_panel` still `--deselect`ed (long-standing
`io_test` chip-data pollution). The two `test_orchestrator_files.py` tests need
Ollama running (they fail, not skip, without it).

**Committed** `629db42` — the whole `io-window-glass` backlog since `346aa3c`
(web answers, decide pipeline, media library, soniox, glass UI + the above) in
one commit. **Build**: `.\dev.ps1 build` OK → `dist/IO/IO.exe` (24.8 MB).

---

## Tasks & Collections — implemented (2026-09-10/11, branch `io-window-glass`)

All 26 tasks / 5 phases done (Groups A-K), task-reviewed group by group,
final full-suite check green. Ledger with every deviation, review finding,
and fix round: `.superpowers/sdd/2026-09-10-tasks-and-collections/progress.md`.
New knowledge doc `.claude/knowledge/tasks-and-collections.md` (the
authoritative write-up — read it before touching completion/roll-forward/
collections code); `query-pipeline.md` and `data-model.md` updated in place.

- **Completion**: `io_assistant/tasks/complete.py` (`set_record_status` — the
  sole `status`/`completed_at` writer; `close_record` — pure-Python
  rapidfuzz match, no model). Orchestrator precheck regex +
  `complete_record` capability (combined-decide) both funnel into it; an
  ambiguous match gates on `PendingComplete`, resolved next turn by ordinal/
  fuzzy pick in Python. `records.completed_at` (migration 0008). Interactive
  checkbox in `card.js`/`records.js` → `PATCH /record/{id}`.
- **Default-today + roll-forward**: a bare `task`/`chore` with no date
  defaults `due_at = start_of_day(now)` unless "someday"-phrased
  (`resolve/dates.py::is_someday_phrase`); `query/compile.py` OR-clause keeps
  an overdue open record in-window regardless of the query's time window
  (read-time, no daily job); `rank.py` gives overdue open records a +0.2
  score bump; `respond.py` adds `overdue`/`due_label` to every row.
- **Collections registry**: migration 0009 `collections` table +
  `io_assistant/collections/registry.py` (`upsert_collection`,
  `describe_collections`, `resolve_collection`, `checkable_kinds`,
  `seen_kinds`, `routing_preamble`). The extraction model proposes a list
  descriptor once per novel kind (`ExtractedRecord.collection`); the writer
  upserts it and defaults checkable-collection items to `status="open"`.
  `routing_preamble` is injected into both the query planner context and the
  decide/plan context so a registered list's slug is reused instead of
  fragmenting.
- **Surfaces**: `CollectionCard` (replaces the generic `TaskListCard` when
  every returned row belongs to one registered collection), `GET
  /collections`, records-browser filter chips, `io list` / `io list <name>`
  CLI (read-only). `aggregation: "count"` compiled end-to-end
  (`compile_count` → synthetic `_Count` row → `pop_count` before ranking →
  `QueryAnswer.count`, phrased via `Responder.run(..., force=True)`).

**Full suite: 501 pass / 11 skip / 1 deselected** (`test_service_standby.py::
test_standby_panel` — the pre-existing `io_test` chip-data pollution fail,
unrelated to this feature). Deferred backlog consolidated into
`.claude/state/backlog.md` under "Tasks & Collections follow-ups". Not yet
re-verified live against the running desktop app in this session (see backlog).

---

## Tasks & Collections — spec written (2026-09-10, branch `io-window-glass`)

Spec `docs/superpowers/specs/2026-09-10-tasks-and-collections-design.md`
(commit `7f8300e`), approved. Plan
`docs/superpowers/plans/2026-09-10-tasks-and-collections.md` (commit `479270f`) —
**26 TDD tasks, 5 phases, ready to execute.** Decisions:
- Bare `task`/`chore` with no date → **due today, rolls forward** (read-time
  rule, no daily job); "someday/eventually" stays dateless.
- Completion via **chat OR checkbox** → one deterministic `close_record` path
  (scoped retrieve + rank; confident → flip `status`, ambiguous → gate). Model
  gives intent + phrase only.
- **Learned `collections` registry** (migration 0009): model proposes
  `{name,item_noun,synonyms,checkable}` on the first list item, Python upserts
  by `kind_slug`; `describe_collections()` injected into `plan.txt`/extract so
  ad-hoc lists ("movies to watch") stay findable.
- 5 phases: (1) completion + interactive checkbox, (2) default-today +
  roll-forward, (3) collections storage, (4) collections-aware routing +
  `aggregation` count branch, (5) `CollectionCard` + records-browser filter +
  optional `io list`.
- New migrations: `0008_task_completion` (`records.completed_at`),
  `0009_collections`. Deferred: per-instance recurring-chore completion, typed
  collection fields, real nag/notifications, snooze.
