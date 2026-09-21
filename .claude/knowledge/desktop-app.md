# Desktop app + local service (Plan 3, 2026-09-08)

The Orchestrator runs behind a local FastAPI service. `io serve` is headless;
`io run` also opens a `pywebview` window.

## Service — `io_assistant/service/`

- `app.py` — `create_app(config, *, orchestrator=None, engine=None) -> FastAPI`.
  Builds (or accepts, for tests) exactly one engine + `sessionmaker` +
  `Orchestrator`, stashed on `app.state`. `Orchestrator.handle` owns a session
  per call, so the service never holds one between requests.
  - `GET /` → `{"service": "io", "status": "ok"}`
  - `GET /health` → `{ok, database, backend_provider}` (`SELECT 1` probe)
  - `POST /utterance` — `{text, source, confirm_token?}` → `{intent, message,
    pending_token?, stored}`. The confirmation gate is carried across calls in
    `app.state.pending: dict[token, PendingStore]` (in-memory, single-user).
    Reply "yes" with the returned `pending_token` to confirm.
  - `WS /ws` — same logic; client sends `UtteranceIn` JSON frames, server
    replies `{"type": "answer", ...}` or `{"type": "error", "message": ...}`.
    One frame per answer — token streaming is deferred.
- `runner.py` — `run_service(config, *, block=True)` (uvicorn; `block=False`
  returns `(server, thread)` after `/health` goes green) and
  `open_window(url, *, title="IO", fullscreen=True)` (lazy `import webview`;
  clear RuntimeError + browser fallback if pywebview is unavailable). Window
  geometry (size/pos) persists to `~/.local/share/io/window.json` on close and
  is restored on open; a first run with no saved geometry opens fullscreen when
  `config.ui.fullscreen`. Native menu: File→New Conversation, View→Reload /
  Toggle Fullscreen. `min_size=(960, 640)`, default `1180×760`, `text_select`.
- `schemas.py` — `UtteranceIn` / `TurnResponse` / `VoiceOut` / `HealthOut` /
  `VoiceHealthOut` / `MessageOut` / `ConversationOut` / `ConversationSummary` /
  `NewConversationOut` (`UtteranceOut` kept as a deprecated alias).

## Frontend — `frontend/` (Nocturne client, served at `/app/`)

Vendored static ES modules, no build step, **no CDN** (local-first —
`tests/test_frontend_assets.py` fails on any non-local `http(s)://` or
`@import url(http…)`; fonts must stay under the byte budget).

- `tokens.css` — **two themes behind one variable set** (layout is identical;
  only the palette swaps). `:root` = **dark** (default, Nocturne — `#1b1d2b`
  panels, `#12131b` ground with an accent glow, `--glass: none`);
  `:root[data-theme="light"]` = **pearl glass** (translucent whites,
  `blur(34px)`, `#c9c6d4` ground). Semantic tokens: `--pearl/-2/-3` (surfaces),
  `--pearl-edge`, `--ink/-2/-3` (text), `--hair/-strong`, `--sheen/-2`,
  `--fill/-2/-strong`, `--hover`, `--wash`, `--scrim`, `--shadow-drop/-2`,
  `--rec`, `--link`, `--sheet`, `--win-bg`, `--body-bg`. Accent ramp
  `--color-accent-*` (`#9184d9`) is shared. Same 5 `@font-face` (local woff2:
  Inter 300/400/500, IBM Plex Mono 400/500 — thin display weights fall back to
  300). `app.css` — every component style, all colours via tokens.
  - `index.html` has an inline head `<script>` that applies the saved theme
    (`localStorage["io.theme"]`, default `"dark"`) to `<html data-theme>`
    before first paint. Settings → **Appearance** toggles it (`.theme-toggle`).
    Separate from `data-acrylic` (window-effect hint, light only).
- `vendor/` — `icons.js` (inlined Phosphor SVG paths + `icon(name, {size})`),
  `markdown.js` (hand-rolled: headings/lists/bold/italic/code/fences/tables/
  quotes/links; non-local hrefs degrade to text; ```mermaid → labelled `<pre>`),
  `recorder.js` (`WavRecorder` + pure `encodeWav()` 16 kHz downsample).
- `state.js` — `createStore(initial)` (`get`/`set`/`update`/`subscribe`, shallow
  merge). `api.js` — `Api(base)` REST + `connectWs(onFrame)` (auto-reconnect).
- `app.js` — shell: `#topbar` (window dots + `IO` wordmark + `#status` readout +
  gear) over `#view`, plus the `#settings` sheet. `VIEWS = {standby, talk,
  conversation, library}` (`gallery` / `files` alias → `library`). `route()`
  clears `#status` between views. `speak(audio_b64)` decodes base64 → `Audio`;
  Esc / view-change stop playback. `window.__ctx` is exposed for the DOM smoke.
- `views/standby.js` (orb + single-line `HH:MM` clock + date + agenda list from
  `/standby` chips + ask-bar pill with mic / folder / history shortcuts),
  `views/listening.js` (mic-live orb, `WavRecorder` → `POST /voice`, VAD/gain
  readouts, ⌥Space / Esc), `views/conversation.js` (persistent 268px history
  rail + `.convo-head` + `#thread` + composer pill + `#inspector` slot; record
  cards render as inline entity pills; `sendTurn()` / `appendUserLine()` /
  `renderAssistant()`), `views/library.js` (mockup 3c — `mount` is the folders
  nav + photo grid + right inspector view; `mountFolders` is the compact folder
  manager the settings sheet embeds; merged the old `files.js` + `gallery.js`).
- `components/` — `orb.js` (`Orb(el, {mode,size})`, modes standby/listening/
  thinking/speaking, `setLevel`), `composer.js` (auto-grow textarea, Enter=send;
  `{setBusy, setStatus, focus, clear}` — `setStatus(stage)` shows a spinner +
  live pipeline stage over the field, driven by `/ws` progress frames),
  `bubble.js`, `card.js` (`record` / `tasklist` / `sources` / `files`),
  `inspector.js` (Memory Inspector panel), `history.js` (`HistoryList(el, ctx)`
  → grouped conversation rail + search field (presentational) + New chat;
  replaced the slide-over `drawer.js`).
- `typing.js` — `revealText(el, text, {cps, minThinkMs})`: hold for
  `min_think_ms`, then type at `typing_cps` (accelerates past 240 chars);
  returns `cancel()` that completes instantly. Pacing comes from
  `config.ui` (`typing_cps`, `min_think_ms`).

## Tests

- `tests/test_frontend_assets.py` — files exist, no external URLs, font budget,
  `node --check` on every JS when node is present, `/app/` served.
- `tests/test_frontend_{markdown,typing,recorder}.py` — pure-JS behaviour run
  through `node` (imports use `Path.as_uri()` for Windows).
- `tests/test_frontend_smoke.py` (`-m ui`, `IO_UI_TESTS=1`) — Playwright Chromium
  headless against the `ui_page` fixture (stub server serving `frontend/` +
  canned `tests/fixtures/ui/*.json`). One-time: `uv run playwright install
  chromium`. Skips cleanly when opt-out / playwright / chromium absent.

## Conversation layer (Phase 1.5)

- `io_assistant/conversation/` — `ConversationStore` (CRUD on the
  `conversations` / `messages` tables from migration `0003`) + `format_context`
  (recent turns → a capped `you:` / `io:` string). The **service** owns the
  tables; `Orchestrator` never touches them (the CLI passes `history=None`).
- Per turn (`/utterance`, `/voice`, `/ws`): `ensure_active()` → append the user
  message → `format_context(recent_turns())` → `orchestrator.handle(text,
  history=…)` → append the assistant message.
- `Backend` gains `context=` on `route`/`plan`/`phrase` and a new
  `acknowledge(facts, context=)` — the STORE reply is a natural sentence, not a
  template. `acknowledge` may only restate `build_fact_list()` output (rows
  `persist_store` wrote) — LLM boundary intact.
- Every turn endpoint returns **`TurnResponse`**: `kind` (answer|ack|gate|
  unknown|error), `intent`, `text`, `shape`, `cards`, `pending_token`,
  `conversation_id`, `message_id`, `audio_b64`. `cards` are `record` /
  `tasklist` / `sources` (`orchestrator_cards.py`).
- `GET /conversation(s)`, `POST /conversation`; `GET /entity/{etype}/{id}` (the
  Memory Inspector — deterministic facts + confidence from vector similarity);
  `GET /standby` (greeting name, `memories`/`recall_ms`/`clock`, surfaced chips).

## Voice in the service (Phase 1.5)

- `POST /voice` — multipart WAV in → `WhisperTranscriber` → the same turn flow →
  `PiperSpeaker.synthesize` → `VoiceOut` (`TurnResponse` + `transcript` +
  `audio_b64`). `GET /voice/health`. `service/voice.py:VoiceModels` builds
  Whisper/Piper lazily on the first `/voice` hit; `503` with a reason when a
  model is missing.
- `POST /voice/transcribe` — batch STT only, no turn (`{transcript, confidence}`).
  The ask-bar mic and the caption box use it. **Always mounted** (needs only
  `app.state.voice`) — it used to live under `if config.files.enabled` as
  `/files/transcribe`, so the mic silently 404'd whenever files were off.
  Whisper is batch: transcribes on release, no partial words.
- **Real-time STT.** `voice.stt_provider` picks the mode; `GET /voice/stt` →
  `{provider, streaming}` and the frontend chooses. `frontend/mic.js:
  createMic(ctx,{onText})` is one abstraction over all three; any hard failure
  falls straight back to batch Whisper (`/voice/transcribe`).
  - **`"whisper-stream"`** (default, fully local) — `io_assistant/transcribe/
    streaming.py:StreamingWhisper`: a rolling faster-whisper loop. `WS
    /ws/transcribe` — browser (`frontend/vendor/localstream.js:LocalStream`)
    streams 16 kHz PCM16 binary frames; the server re-transcribes the
    un-committed tail every 0.4 s (commits segments older than ~2 s, keeps the
    last 2 s provisional → text self-corrects), pushes `{type:"partial"}` and
    one `{type:"final"}`. First use downloads `whisper_stream_model`
    (`large-v3-turbo`, ~1.5 GB); GPU strongly preferred.
  - **`"soniox"`** (cloud, opt-in — `rules/local-first.md` path #2) —
    `transcribe/soniox.py:mint_temp_key` trades the real `SONIOX_API_KEY` for a
    short-lived token; the browser (`vendor/soniox.js:SonioxStream`) streams
    straight to `wss://stt-rt.soniox.com`. `POST /voice/stream-token` (503 if
    off / no key). IO never proxies audio.
  - **`"whisper"`** — batch, on release.
  - `vendor/pcm.js` — shared `downsample` + `pcm16` for both stream paths.
- **Input focus** never shows a ring — the container just shifts fill on
  `:focus-within` (per the Apple-adjacent direction). Buttons keep the
  keyboard `:focus-visible` glow; text fields never.
- `PiperSpeaker` now synthesises **sentence by sentence** with inter-sentence
  silence and a tuned `SynthesisConfig` (`speak/speech_text.py` does the text
  prep — abbreviations, times, pauses). Default voice `en_US-hfc_female-medium`.
- `io listen` is a thin client of `POST /voice` (`voice/client.py:ServiceClient`
  + `voice/loop.py:VoiceLoop`) — capture stays local, transcribe + synth are the
  server.

## Packaging (Phase 2B)

- `scripts/make_icon.py` — `assets/io-logo.png` → `assets/io.ico`
  (16/32/48/64/128/256) + `assets/io-512.png`; both generated files are
  git-ignored. `make_icon(src, ico_out, png_out)`.
- `io_assistant/service/singleton.py` — `acquire_single_instance(name=
  "io-assistant")` returns a held `SingleInstance` or `None` (Windows: `Global\\`
  named mutex; POSIX: `flock` on `~/.local/share/io/<name>.lock`).
  `surface_running_instance(config)` opens the running app's `/app/` URL in the
  browser and prints a line — never starts a service.
- `cli.run()` calls `acquire_single_instance()` first; `None` →
  `surface_running_instance()` + `SystemExit(0)`; else the window runs inside
  `with inst:`. `io_assistant/app_entry.py` is the frozen entry point (thin
  wrapper over `cli.run`).
- `load_config` search order: explicit path → `./config.toml` →
  `~/.config/io/config.toml` → the bundled repo-root `config.toml`
  (`config.py:config_source()`). So a frozen user can override the bundled
  default without touching the read-only bundle.
- `packaging/io.spec` — PyInstaller **one-dir**, windowed, `name="IO"`,
  `icon=assets/io.ico`, entry `io_assistant/app_entry.py`. Bundles `frontend/`,
  `config.toml`, `alembic.ini`, `db/migrations/`, `prompts/`, `assets/io-512.png`.
  Module-level `ENTRY` / `DATAS` are read by `tests/test_packaging_spec.py`
  (guarded so `runpy` can import it without PyInstaller globals). **Not**
  bundled: PostgreSQL, the Whisper/Piper models.
- `dev.ps1 build` → generate icon + `pyinstaller packaging/io.spec` → `dist/IO/
  IO.exe`. `dev.ps1 install` → Desktop shortcut to `dist\IO\IO.exe` (runs
  `build` if the exe is missing).
- **Full-featured bundle (Phase 2B.1).** `io.spec` now bundles **voice** too —
  `collect_all` for `piper` / `faster_whisper` / `sounddevice` / `ctranslate2` /
  `onnxruntime` / `av`, plus `packaging/hooks/hook-webrtcvad.py` overriding the
  broken contrib hook. `torch` stays excluded (faster-whisper uses ctranslate2).
  Voice **models** still download on first use — `VoiceModels._ensure_voice_model`
  fetches the Piper `.onnx` via `piper.download_voices` on the first `/voice`
  synth; faster-whisper auto-downloads its model.
- **DB bootstrap on launch** — `io_assistant/service/bootstrap.py`:
  `ensure_database(config)` pings Postgres, runs `docker compose -p io -f
  <bundle>/docker-compose.yml up -d db` if it's down, waits ~60 s, then
  `alembic upgrade head`. `cli.run()` / `cli.serve()` call it first;
  `runner.error_dialog(msg)` (a pywebview window) shows a `BootstrapError`
  (e.g. "Docker Desktop isn't running"). The bundle ships `docker-compose.yml`
  + `scripts/initdb/`. **The one prerequisite is Docker Desktop running.**
- **Verified**: build completes; `dist/IO/IO.exe` (~25 MB exe / ~350 MB bundle)
  starts its own DB container, migrates, serves `/health` + `/voice/health`
  (whisper code present) + `/standby` with real data; a second launch opens
  `/app/` in the browser and exits.
- `packaging/io.spec` has `IO_BUILD_CONSOLE=1` → a console EXE for debugging.
- **Manual, Windows-only.** macOS/Linux packaging, code signing, `.msi`,
  auto-update, bundling the voice *models*, and an embedded Postgres are backlog.

## Shell UI (pearl glass, Phase 2B.1 — reskin 2026-09-09)

Design ref: `docs/design/IO Glass.dc.html` (imported from the "IO UI Mockups"
Claude Design project). The dark Nocturne shell was replaced wholesale by a
light frosted-glass look — no theme toggle.

- **One floating glass card.** `.win` is `border-radius:20px` + `1px
  var(--pearl-edge)` + `background:var(--pearl)` + `backdrop-filter:var(--glass)`
  + `--shadow-window`. Body ground is `--ground #c9c6d4`; under the Win11
  acrylic backdrop `app.js` sets `data-acrylic="1"` and the ground drops toward
  transparent so the real wallpaper reads through the blur.
- **`#topbar`** (44px) — left: `.winctl` = three filled icon buttons (minimize
  / fullscreen / close) wired to `pywebview.api`; centre: `IO` wordmark; right:
  `#status` readout + settings gear.
- **The window is never draggable** — `runner.py` `easy_drag=False` and the
  topbar has no `app-region: drag`. `js_api.toggle_fullscreen()` returns the
  new bool (`is_fullscreen()` too); `app.js` mirrors it to
  `<html data-fullscreen>` and CSS squares off the frame.
- **Apple-adjacent styling** — no borders/outlines on buttons, inputs or
  cards; soft filled surfaces (`--fill` / `--fill-strong`), soft focus rings
  (`box-shadow` accent glow, never `outline`), iOS-style segmented control for
  the theme toggle. Structural hairlines (`--hair`) are kept only for list-row
  separators.
- **View transitions** (`app.js route()` + `#view.leaving`/`.entering` CSS) —
  outgoing `#view` fades out (120 ms), then mounts and staggers the new view in
  big→small: structure (orb, panels) 0 ms, primary content 70 ms, controls
  140 ms, text/tiles/chips 210 ms. Reduced-motion → instant. Because mount is
  deferred, cross-view sends go through **`ctx._pending`**: the source view
  sets it + `goto("conversation")`, and `conversation.js` fires `sendTurn` once
  mounted (standby ask bar, library "ask about this", the `.lib-ask` bar).
- **Lightbox** (`components/lightbox.js`) — double-click an image/video tile
  (or click the inspector preview) → full-screen viewer, click backdrop / ✕ /
  Esc to close, fades + scales.
- **Keys** (global, `app.js`): `Esc` closes settings / returns to standby;
  `Alt+Enter` toggles fullscreen; `⌥/Alt+Space` toggles voice on standby.
  Alt+Space is left for voice only.
- **`frontend/index.html`** is `#topbar` + `#view` + `#settings` sheet (glass,
  slides from the right) + its scrim. No `#drawer` (history is now inline in the
  conversation view). The gear opens `components/settings.js` — voice toggle +
  **folder management** (mounts `library.mountFolders`).
- **Standby 3a** (`views/standby.js`): orb (250px) beside a **two-row clock**
  (`.clk-h` over `.clk-m`, `clamp(72px,13vw,148px)`) with `.clk-when` (weekday
  over month-day, mono caps) stacked to its right; a hairline, then the
  **agenda list** (`.agenda-row` per `/standby` chip). Ask bar `.askbar` pill:
  mic + auto-growing `<textarea>` (Enter sends, Shift+Enter newline, wraps up to
  132px) + folder shortcut (→ library) + history shortcut (→ conversation) +
  send. On submit the pill flashes `.askbar.busy` ("Working…") before the view
  swaps. No visible keyboard hint (Alt+Space still works for voice).
  - **Rotating placeholder** — `EXAMPLES[]` (one prompt per feature) shuffled
    and cycled through the placeholder every 4.5 s (`.ph-fade` colour fade);
    freezes once the user types.
  - **Voice feedback** — clicking the mic (or ⌥Space, toggle) enters a
    `.recording` state: orb → `listening` mode with a live level meter, the
    input row swaps to `.askbar-live` (waveform bars + label + elapsed). With
    Soniox the label shows the **live interim transcript** (`.askbar-live-label`
    clips left-first so you see the latest words); with Whisper it shows
    `Listening…` then `Transcribing…`. On stop it submits the final text.
- **Conversation 3b** (`views/conversation.js` + `components/history.js`): a
  persistent 268px `.convo-side` rail (back chevron + presentational search +
  grouped chat list + New chat) beside `.convo-main` (`.convo-head` orb/title/
  counts, `#thread`, composer pill). User bubbles = pearl pills; IO answers get
  a row of entity **pills** built from `record` cards (tasklist/sources still
  render via `card.js`). `#inspector` slot unchanged.
- **Library 3c** (`views/library.js`): `.lib-nav` (folders + "Choose folder…" +
  SHOW filters All/Photos/Videos/Voice notes/Documents + "Back to chat") |
  `.lib-main` (breadcrumb + `.lib-grid` + folder-level ask pill) | `.lib-insp`
  (preview, path, editable `IO's caption` + gate, linked-record pills, "Ask
  about this"). Merges the former `files.js` + `gallery.js`.
  - `/files/open` now lists **every file** (`walk_dir(..., include_all=True)`),
    not just media: non-media get `media_kind` `"doc"` (indexable text) or
    `"file"` (other), `raw_url` + `size_bytes`, `indexed=false`, no thumb.
    They land in the Documents filter. Grid renders the first 400 + a
    "+N more" tile.
  - Thumbnails are square (`aspect-ratio:1`), media `object-fit: contain`
    (letterboxed), non-media a centred glyph.
- **Orb** (`components/orb.js`) unchanged structurally — mounts its own
  fixed-size `.orb` inside the host; the glass palette retunes it in `app.css`.
- **Views**: `standby` (default) / `talk` / `conversation` / `library` /
  `records`. Topbar has a brain icon → `records` and the gear → settings.
  `#view { min-height: 0 }` is load-bearing — without it flex children grow to
  fit content and nothing scrolls.
- **Memory browser** (`views/records.js`, `GET /records`) — every stored
  record, editable title (contenteditable → `PATCH /record/{id}`, re-embeds),
  editable date (prompt → re-ground), inline delete (`DELETE /record/{id}`,
  two-tap confirm), domain filter chips. Also `DELETE /entity/{etype}/{id}`.
  The place to clean up bad extractions.
- **Library** additions: grid ⇄ list view + a size stepper in the breadcrumb
  (`localStorage["io.lib.view"|"io.lib.size"]`, `.lib-grid[data-view][data-size]`
  CSS); each folder in the nav has a hover **× (forget)** →
  `ctx.api.forgetFile`; the "Back to chat" is now a prominent filled icon at
  the top of the nav. Double-clicking a text file (`.md/.js/.ts/.txt/…`) opens
  it in the lightbox (`Lightbox({text,name})` → `<pre>`).
- **Typing** (`typing.js`) now steps on `setTimeout` (not rAF) and completes
  instantly when `document.visibilityState === "hidden"` — a minimised window
  no longer freezes a mid-reveal transcript.
- Static assets: `Cache-Control: no-store, must-revalidate` + `Pragma:
  no-cache`, ETag/Last-Modified stripped (`_NoCacheStatic` in `app.py`) so a
  rebuild always wins over any cache.

## Deferred

State 1d task runner (agent loop); external-source provenance; entity-file
browser; token streaming over `/ws`; real Mermaid; Kokoro `Speaker` adapter.


## Self-update (2026-09-21)

The git checkout is the install. `io_assistant/updates/`: `check.py`
(`find_repo`, `check` → `UpdateStatus`; plain `git fetch`/`rev-list`/`log`),
`apply.py` (`UpdateChecker` daemon thread — production only, i.e. when
`create_app` owns its engine — and `spawn_update`), `localize.py`
(`split_local`: move edits to `config.toml` into the gitignored
`config.local.toml`; `load_config` deep-merges local over base).
Service: `GET /update[?refresh=1]`, `POST /update/apply` (409 unless an update
is available and the tracked tree is clean) → spawns detached
`scripts/update.ps1` and exits IO after 1 s. The script snapshots the DB
(`~/.local/share/io/backups/pre-update-<sha>.sql`, keeps 3, ~100 MB each on a
real DB), `git pull --ff-only`, `uv sync`, rebuilds `dist\IO\IO.exe` if it
exists, relaunches; on failure it resets HEAD only if the pull moved it.
Migrations apply on the next launch. `[updates] branch = ""` = the current
branch; a branch with no remote counterpart reports no update.
UI: topbar `#update-pill`, Settings → Updates (`frontend/updates.js` holds the
wording; two-tap "Update & restart"). `io update --check | --localize`.
