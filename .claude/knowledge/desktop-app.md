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

- `tokens.css` — Nocturne `:root` tokens (`--color-bg #161826`, blurple accent
  `#9184d9` used as line + glow never flood, radii 4/8/14) + 5 `@font-face`
  (local woff2 in `vendor/fonts/`: Inter 300/400/500, IBM Plex Mono 400/500).
  `app.css` — every component style.
- `vendor/` — `icons.js` (inlined Phosphor SVG paths + `icon(name, {size})`),
  `markdown.js` (hand-rolled: headings/lists/bold/italic/code/fences/tables/
  quotes/links; non-local hrefs degrade to text; ```mermaid → labelled `<pre>`),
  `recorder.js` (`WavRecorder` + pure `encodeWav()` 16 kHz downsample).
- `state.js` — `createStore(initial)` (`get`/`set`/`update`/`subscribe`, shallow
  merge). `api.js` — `Api(base)` REST + `connectWs(onFrame)` (auto-reconnect).
- `app.js` — shell: titlebar + left rail (`NAV`) + drawer + `#view`. `VIEWS =
  {standby, talk, conversation}`; rail "Conversation" toggles the drawer, stub
  nav lands on the transcript. `speak(audio_b64)` decodes base64 → `Audio`;
  Esc / view-change stop playback. `window.__ctx` is exposed for the DOM smoke.
- `views/standby.js` (greeting, stat row, big orb, surfaced chips, composer),
  `views/listening.js` (mic-live orb, `WavRecorder` → `POST /voice`, VAD/gain
  readouts, ⌥Space / Esc), `views/conversation.js` (`#thread` + compact composer
  + `#inspector` slot; `sendTurn()` / `appendUserLine()` / `renderAssistant()`).
- `components/` — `orb.js` (`Orb(el, {mode,size})`, modes standby/listening/
  thinking/speaking, `setLevel`), `composer.js` (auto-grow textarea, Enter=send),
  `bubble.js`, `card.js` (`record` / `tasklist` / `sources`), `inspector.js`
  (Memory Inspector panel), `drawer.js` (conversation list grouped Today/
  Yesterday/Earlier, `+ New`, history hydrate).
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

## Shell UI (minimal, Phase 2B.1)

- **Frameless + translucent window.** `runner.open_window` →
  `webview.create_window(..., frameless=True, easy_drag=True, transparent=True,
  background_color="#0E0F17")` (falls back to non-transparent on failure).
  `body { background: rgba(14,15,23,.78) }`. The `.win::before` strip is an
  invisible top drag region; `.winctl` (min / fullscreen / close, appear on
  hover, top-right) call `window.pywebview.api.{minimize,toggle_fullscreen,
  close}`. Menu also has File→Quit / View→Minimize.
- **No rail / tabs.** `frontend/index.html` is just `#view` + a floating `#gear`
  (bottom-left) + `#drawer` (conversation history, slides from the left) +
  `#settings` (slides from the right). The gear opens `components/settings.js`
  — voice toggle + **folder management** (it mounts `views/files.js`, the only
  place to add/remove indexed folders now). `views/files.js` "Choose folder…"
  → `window.pywebview.api.pick_folder()` (native OS dialog), text field fallback.
- **Standby** (`views/standby.js`): a two-column stage — the orb (460 px,
  offset left) and a big **vertically-stacked clock** (`HH` over `MM`,
  `clamp(96px,21vw,260px)`, tabular-nums) filling the right; below it the date,
  greeting, chips, and the **ask bar** (`.askbar`: mic + text input + explicit
  circular send button; form submit → `sendTurn`). Alt+Space toggles the mic.
- **Orb** (`components/orb.js`) mounts its own fixed-size `.orb` div **inside**
  the host so layout can't distort the circle; layers centre via
  `inset:0;margin:auto`.
- **Views**: `standby` (default) / `talk` / `conversation` / `gallery`. No nav
  chrome — you reach `conversation` by talking, `gallery` via "open the folder
  X", and Esc / the conversation view's back button return to `standby`. The
  conversation view has a 3-button bar (back / history-drawer / new).
- **Typing** (`typing.js`) now steps on `setTimeout` (not rAF) and completes
  instantly when `document.visibilityState === "hidden"` — a minimised window
  no longer freezes a mid-reveal transcript.
- Static assets: `Cache-Control: no-store, must-revalidate` + `Pragma:
  no-cache`, ETag/Last-Modified stripped (`_NoCacheStatic` in `app.py`) so a
  rebuild always wins over any cache.

## Deferred

State 1d task runner (agent loop); external-source provenance; entity-file
browser; token streaming over `/ws`; real Mermaid; Kokoro `Speaker` adapter.
