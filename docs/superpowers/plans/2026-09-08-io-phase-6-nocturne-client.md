# IO Phase 6 — Nocturne Desktop Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `frontend/` as the Nocturne desktop client — a fullscreen, dark, instrumented chat app with a central voice orb — talking to the Phase 5 service. Three working states: **Standby**, **Listening**, **Conversation + Memory Inspector**. Simulated typing with deliberate pacing.

**Architecture:** Vanilla ES modules, no framework, no build step. Everything is vendored into the repo — Inter + IBM Plex Mono as subsetted woff2, the ~12 Phosphor icons as inline SVG, the Nocturne token sheet. A tiny hand-rolled state store + a `fetch`/WS API client drive three view modules and a set of components. Pure logic (markdown, the typing scheduler, the WAV encoder) lives in testable modules.

**Tech Stack:** HTML + CSS + vanilla ES2022 modules; `pywebview` for the window. Python test side: the existing `pytest` + a new **optional** Playwright DOM smoke (`@pytest.mark.ui`, `IO_UI_TESTS=1`). No npm/node toolchain is added to the build.

**Spec:** `docs/superpowers/specs/2026-09-08-io-phase-1.5-conversational-shell.md` §2 (Nocturne), §7 (the client). **Visual source of truth:** `docs/design/IO Desktop.dc.html` (the four-state mockup) and `docs/design/nocturne/` (`styles.css` tokens, `readme.md`).

## Global Constraints

- **Local-first (hard rule):** `frontend/` references **zero** external URLs — no
  Google Fonts `<link>`, no unpkg, no `@import url(http…)`. Fonts and icons are
  files in the repo. `tests/test_frontend_assets.py` fails the build on any
  non-local `http(s)://` and on `@import url(`.
- **No build step.** Browsers load `frontend/*.js` as ES modules directly.
  `pywebview` on Windows uses Edge WebView2 (Chromium) — modern JS is fine.
- **Nocturne is the design.** Every colour, radius, font size, and animation
  comes from `docs/design/nocturne/styles.css` tokens or matches
  `docs/design/IO Desktop.dc.html`. Do not invent parallel values. Accent
  `#9184d9` is a line and a glow, never a flood.
- **Themed interaction states:** `:focus-visible { outline: 2px solid
  var(--color-accent); outline-offset: 2px }`, hover/press tints from the accent
  ramp, `::selection` an accent tint. `@media (prefers-reduced-motion: reduce)`
  freezes orb rotation and the caret.
- The service (Phase 5) must be running for the app to do anything; `io run`
  starts or reuses it. Tests mock the API client, never the DOM.
- Fonts: subset to Latin + the punctuation the UI uses; target < 45 KB total for
  all five faces. Vendor the Phosphor SVGs used by the mockup only.

---

## File Structure

```
frontend/
  index.html                 # shell markup + <link> to local tokens.css / app.css
  app.js                     # boot: state store, router, api client, mount active view
  tokens.css                 # Nocturne :root vars + ramps (from docs/design/nocturne/styles.css) + app additions
  app.css                    # component styles (shell, rail, bubbles, cards, composer, orb)
  vendor/
    fonts/                   # Inter-{300,400,500}.woff2, IBMPlexMono-{400,500}.woff2 + @font-face in tokens.css
    icons.js                 # export ICONS: { waveform, chatDots, brain, listChecks, usersThree, gear, mic, circle, checkCircle, check, arrowUp, spinner } -> SVG strings
    markdown.js              # renderMarkdown(src) -> HTML  (pure; upgraded from Plan 3)
    recorder.js              # WavRecorder: start()/stop() -> 16 kHz mono PCM16 WAV Blob  (pure-ish)
  state.js                   # createStore(initial): { get, set, update, subscribe }
  api.js                     # Api(base): health, standby, sendText, sendVoice, conversation, conversations, newConversation, entity; connectWs()
  typing.js                  # revealText(el, text, { cps, minThinkMs, onDone }) -> cancel()  (pure scheduler)
  views/
    standby.js               # mount(root, ctx)
    listening.js
    conversation.js
  components/
    orb.js                   # Orb(el, { mode })  -> setMode(m); modes: standby|listening|thinking|speaking
    bubble.js                # userBubble(text), ioBubble() -> { el, body, setStreaming }
    card.js                  # renderCard(card) -> el   (record | tasklist | sources)
    inspector.js             # mountInspector(root, panelData)
    composer.js              # Composer(root, { onSend, onMic, compact }) -> { setBusy, focus }
tests/
  test_frontend_assets.py          # updated: fonts+icons local, no @import url(http
  test_frontend_markdown.py        # runs frontend/vendor/markdown.js via node when present
  test_frontend_typing.py          # runs frontend/typing.js via node when present
  test_frontend_smoke.py           # @pytest.mark.ui  Playwright: boot + 3 views render
```

---

## Task 1: Vendor fonts, icons, and the Nocturne token sheet

**Files:**
- Create: `frontend/vendor/fonts/*.woff2`, `frontend/vendor/icons.js`,
  `frontend/tokens.css`
- Delete: `frontend/vendor/markdown.js` is kept (upgraded in Task 6); the old
  `frontend/styles/app.css`, `frontend/components/message.js`,
  `frontend/views/{chat,timeline,sources,review}.js`, `frontend/app.js`,
  `frontend/index.html` are replaced across this plan — remove them in Task 2.
- Test: `tests/test_frontend_assets.py`

**Interfaces:**
- Produces:
  - `frontend/vendor/fonts/` — `Inter-300.woff2`, `Inter-400.woff2`,
    `Inter-500.woff2`, `IBMPlexMono-400.woff2`, `IBMPlexMono-500.woff2`,
    subset to Latin + `–—·⌥…°%£$`. Sourced from the upstream repos
    (rag/inter, IBM/plex) or `google-webfonts-helper`; **committed to the repo**.
  - `frontend/tokens.css` — the Nocturne `:root` block copied verbatim from
    `docs/design/nocturne/styles.css` (all `--color-*` ramps, `--space-*`,
    `--radius-*`, `--shadow-*`, `--font-*`), **plus** app additions:
    `--color-page: #0f111c`, `--color-panel: #1b1d2b`, `--color-hair: #292b31`,
    `--color-hair-2: #33364a`, `--orb-core: radial-gradient(circle at 38% 34%,
    #d2cefd, #796cbf 58%, #423a6a)`, and the five `@font-face` rules pointing at
    `./vendor/fonts/*.woff2` with `font-display: swap` and the real fallbacks
    (`Inter` → `system-ui`; `"IBM Plex Mono"` → `ui-monospace`). No `@import`.
  - `frontend/vendor/icons.js` — `export const ICONS = { … }` mapping the 12
    names to inline `<svg viewBox="0 0 256 256" fill="currentColor">…</svg>`
    strings copied from Phosphor's regular set (`waveform`,
    `chat-teardrop-dots`, `brain`, `list-checks`, `users-three`, `gear`,
    `microphone`, `circle`, `check-circle`, `check`, `arrow-up`, and a
    `spinner` — a plain `<circle>` with `stroke-dasharray` for CSS rotation).
    Plus `export function icon(name, {size=18, cls=""}={})` → an `<svg>` string.

- [ ] **Step 1: Update the failing asset test** — `tests/test_frontend_assets.py`

```python
import re
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
_EXT_URL = re.compile(r"https?://(?!(127\.0\.0\.1|localhost))", re.I)
_IMPORT_URL = re.compile(r"@import\s+url\(\s*['\"]?https?:", re.I)


def test_core_files_exist():
    for p in ["index.html", "app.js", "tokens.css", "app.css",
              "vendor/icons.js", "vendor/markdown.js", "state.js", "api.js",
              "typing.js"]:
        assert (FRONTEND / p).is_file(), p
    fonts = list((FRONTEND / "vendor" / "fonts").glob("*.woff2"))
    assert len(fonts) >= 5


def test_no_external_urls():
    bad = []
    for path in FRONTEND.rglob("*"):
        if path.suffix.lower() in {".html", ".js", ".css"}:
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _EXT_URL.search(line) or _IMPORT_URL.search(line):
                    bad.append(f"{path.relative_to(FRONTEND)}:{i}: {line.strip()}")
    assert not bad, "external ref(s):\n" + "\n".join(bad)


def test_font_total_under_budget():
    total = sum(p.stat().st_size for p in (FRONTEND / "vendor" / "fonts").glob("*.woff2"))
    assert total < 60_000, f"fonts total {total} bytes — subset harder"
```

- [ ] **Step 2: Run, watch it fail** — `test_core_files_exist` fails (no
  `tokens.css`, no fonts).

- [ ] **Step 3: Vendor the fonts.** Get the five woff2 files (subset). If a
  subsetting tool is unavailable, download the `latin` woff2 from
  `google-webfonts-helper` (Inter 300/400/500, IBM Plex Mono 400/500) — those
  are already `latin`-subset and land ~8–11 KB each. Commit them under
  `frontend/vendor/fonts/`.

- [ ] **Step 4: Write `frontend/tokens.css`** — paste the Nocturne `:root` from
  `docs/design/nocturne/styles.css`, add the app tokens and the five
  `@font-face` blocks (local `src: url("./vendor/fonts/Inter-400.woff2")
  format("woff2")`).

- [ ] **Step 5: Write `frontend/vendor/icons.js`** — the `ICONS` map + `icon()`
  helper. Copy each SVG body from https://github.com/phosphor-icons/core
  `assets/regular/<name>.svg` (that's a repo file, fetched once at authoring
  time and inlined — the shipped file has no network reference).

- [ ] **Step 6: Run** — `uv run pytest tests/test_frontend_assets.py -q`.
  `test_core_files_exist` still fails on the not-yet-created `app.js` etc.
  (Task 2); `test_no_external_urls` and `test_font_total_under_budget` PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/vendor/ frontend/tokens.css tests/test_frontend_assets.py
git commit -m "feat(ui): vendor Inter + IBM Plex Mono + Phosphor icons + Nocturne tokens"
```

---

## Task 2: Shell — window chrome, rail, state store, API client, router

**Files:**
- Create: `frontend/index.html`, `frontend/app.js`, `frontend/app.css`,
  `frontend/state.js`, `frontend/api.js`
- Delete: `frontend/styles/app.css`, `frontend/components/message.js`,
  `frontend/views/{chat,timeline,sources,review}.js`
- Modify: `io_assistant/service/app.py` (the static mount already serves
  `frontend/`; no change needed unless the mount path assumptions broke)
- Test: `tests/test_frontend_assets.py` (now passes core-files), a `node`
  sanity check that `app.js` parses

**Interfaces:**
- Produces:
  - `frontend/state.js` — `createStore(initial)` → `{ get(), set(patch),
    update(fn), subscribe(fn) -> unsub }`. Synchronous, shallow-merge, notifies
    subscribers after each change. ~30 lines.
  - `frontend/api.js` — `Api(base = "")`:
    - `health()`, `voiceHealth()`, `standby()`,
      `sendText({text, conversationId, confirmToken}) -> TurnResponse`,
      `sendVoice(wavBlob, {conversationId, speak}) -> VoiceOut`,
      `conversation(id, before) -> {conversation_id, messages}`,
      `conversations() -> [summary]`, `newConversation() -> {conversation_id}`,
      `entity(etype, id) -> panel`.
    - `connectWs(onFrame) -> { send(obj), close() }` — `ws://<host>/ws`,
      auto-reconnect with backoff; used by the composer path as the default
      (falls back to `sendText` POST if the socket is down).
  - `frontend/app.js` — on `DOMContentLoaded`: build the store
    (`{ view: "standby", conversationId: null, transcript: [], busy: false,
    autoSpeak: "voice", voiceOk: false, connection: "connecting" }`), the `Api`,
    open the WS, wire the rail nav (hash `#/standby` `#/talk` `#/conversation`
    plus inert `#/memory` `#/tasks` `#/people` `#/settings`), and mount the
    active view into `#view` on every `view` change. Exposes `ctx = { store, api,
    ws, speak(audioB64), goto(view) }` to views.
  - `frontend/index.html` — the Nocturne shell: `<div class="win">` with the
    36 px `<header class="titlebar">` (three inert dots, `IO 1.4`, a right
    `#status` slot), `<nav class="rail">` (orb glyph + the Phosphor nav +
    `gear`), `<main id="view">`. Links `tokens.css` then `app.css`.
  - `frontend/app.css` — the shell, titlebar, rail, and shared primitives
    (`.mono`, `.kicker`, `.hair`, `.chip`, `.btn` per Nocturne). Sizes and
    colours from `docs/design/IO Desktop.dc.html` §1a chrome.
  - `speak(audioB64)` in `ctx`: decode base64 → `Blob` → `new Audio(URL)` →
    play; track the element so `Esc` / a new turn stops it; feed it to an
    `AnalyserNode` so the orb's `speaking` mode can pulse to amplitude.

- [ ] **Step 1: Write the failing test** — extend `tests/test_frontend_assets.py`

```python
import shutil, subprocess

def test_app_js_parses_if_node_present():
    node = shutil.which("node")
    if not node:
        import pytest; pytest.skip("node not installed")
    for f in ["app.js", "state.js", "api.js", "typing.js", "vendor/markdown.js",
              "vendor/icons.js"]:
        r = subprocess.run([node, "--check", str(FRONTEND / f)], capture_output=True, text=True)
        assert r.returncode == 0, f"{f}: {r.stderr}"
```

- [ ] **Step 2: Run** — `test_core_files_exist` + `test_app_js_parses…` fail.

- [ ] **Step 3: Delete the Plan-3 frontend files** and write `index.html`,
  `app.css`, `state.js`, `api.js`, `app.js` per the Interfaces block. Keep the
  markup minimal — views own their content. The titlebar `#status` text is set
  by the active view.

- [ ] **Step 4: Manual boot check.** `.\dev.ps1 up` then open
  `http://localhost:8765/app/` — the shell renders (dark window, titlebar, rail
  with icons), the console shows the WS connecting, `#view` is empty (no view
  built yet). Fix any 404 on a vendored asset.

- [ ] **Step 5: Run** — `uv run pytest tests/test_frontend_assets.py -q` → PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/ tests/test_frontend_assets.py
git rm -r frontend/styles frontend/components/message.js frontend/views 2>/dev/null || true
git commit -m "feat(ui): Nocturne shell — window chrome, rail, state store, API client, router"
```

---

## Task 3: The orb

**Files:**
- Create: `frontend/components/orb.js`; orb CSS in `frontend/app.css`
- Test: `tests/test_frontend_smoke.py` (adds an orb assertion — `@pytest.mark.ui`)

**Interfaces:**
- Produces:
  - `frontend/components/orb.js` — `export function Orb(el, { mode = "standby",
    size = 340 } = {})`: builds the layered rings from
    `docs/design/IO Desktop.dc.html` §1a/§1b into `el` —
    (1) masked `repeating-conic-gradient` tick ring, (2) a static thin ring,
    (3) a transparent ring with one accent arc (`border-top-color`) spinning
    (`io-spin`), (4) a dashed counter-rotating ring (`io-spinr`), (5) a
    `radial-gradient` halo (`io-halo`), (6) the bright core (`--orb-core`
    + accent glow `box-shadow`) breathing (`io-breathe`), (7) 1–2 orbital blip
    dots (`io-blip`). Returns `{ setMode(m), setLevel(0..1), destroy() }`.
    - `standby`: slow rotations (14–120 s), core visible, halo calm.
    - `listening`: swap the core for the 12-bar `io-bar` waveform, all rotations
      ~3–5×, halo `io-halo` 2.4 s.
    - `thinking`: core dim, one ring gains the fast accent arc.
    - `speaking`: `setLevel(amp)` each animation frame scales the halo/core
      (driven by the `AnalyserNode` in `app.js`).
  - The `@keyframes` (`io-spin`, `io-spinr`, `io-breathe`, `io-halo`, `io-bar`,
    `io-blip`, `io-caret`) live in `app.css`, copied from the mockup's
    `<style>`. All disabled under `prefers-reduced-motion`.

- [ ] **Step 1: Add the `@pytest.mark.ui` smoke skeleton** — `tests/test_frontend_smoke.py`

```python
import os, subprocess, sys, time
import pytest

pytestmark = [
    pytest.mark.ui,
    pytest.mark.skipif(os.environ.get("IO_UI_TESTS") != "1", reason="opt-in; needs Playwright"),
]

# Fixture `ui_page` (added here): starts the app with a stub API via a tiny
# static server that also answers /standby, /voice/health, /utterance, etc. with
# canned JSON, then yields a Playwright page at /app/. Implementation in the
# fixture — see Step 3.

def test_orb_renders_and_switches_mode(ui_page):
    ui_page.goto_view("standby")
    assert ui_page.locator(".orb").count() == 1
    ui_page.eval("window.__ctx.store.set({view:'talk'})")
    assert ui_page.locator(".orb.mode-listening, .orb[data-mode=listening]").count() == 1
```

- [ ] **Step 2: Run** — skipped without `IO_UI_TESTS=1` (fine — it's opt-in).
  If Playwright + a browser are available, `IO_UI_TESTS=1 uv run pytest
  tests/test_frontend_smoke.py` fails (no orb).

- [ ] **Step 3: Implement `orb.js` + the keyframes in `app.css`.** Build the
  Playwright `ui_page` fixture in `tests/conftest.py` (guarded by an import of
  `playwright`): a `threading` HTTP server serving `frontend/` and canned JSON
  for the service routes, `sync_playwright()` launching Chromium headless,
  `page.goto(f"{base}/app/")`, and helpers `goto_view` / `eval`.

- [ ] **Step 4: Manual check** — reload `/app/`, temporarily mount an Orb in
  `#view`; watch the rings rotate and the core breathe; toggle
  `prefers-reduced-motion` and confirm it freezes.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/orb.js frontend/app.css tests/test_frontend_smoke.py tests/conftest.py
git commit -m "feat(ui): the voice orb — layered rings, four modes, reduced-motion aware"
```

---

## Task 4: Standby view

**Files:**
- Create: `frontend/views/standby.js`; `frontend/components/composer.js`
- Test: `tests/test_frontend_smoke.py` (standby assertions)

**Interfaces:**
- Produces:
  - `frontend/components/composer.js` — `export function Composer(root, { onSend,
    onMic, compact = false, placeholder })` → builds the input row from
    `docs/design/IO Desktop.dc.html` §1a (full) / §1c (compact "Reply to IO"):
    a `microphone` icon button, an auto-growing `<textarea>`, and (compact) an
    `arrow-up` send button. `Enter` → `onSend(text)`, `Shift+Enter` newline,
    the mic button → `onMic()`. Returns `{ setBusy(b), focus(), clear() }`.
  - `frontend/views/standby.js` — `export function mount(root, ctx)`:
    `ctx.api.standby()` → render "Good {morning|afternoon|evening}, {name}." (h1,
    Inter 300 26 px), the mono stat row (`{memories} MEMORIES · {recall_ms} ms
    RECALL · {clock}`), a large centred `Orb({mode:"standby"})`, the chip row
    (each chip a `.btn`-ish pill — click sends its `text` as a turn and
    `ctx.goto("conversation")`), and a full `Composer` with the "Ask IO, or hold
    ⌥ Space to talk" hint. Sets the titlebar `#status` to `LOCAL · ENCRYPTED`.
    A `⌥Space` keydown anywhere in this view → `ctx.goto("talk")`.

- [ ] **Step 1: Extend the smoke test**

```python
def test_standby_greets_and_shows_chips(ui_page):
    ui_page.goto_view("standby")
    assert "Good " in ui_page.locator("h1").inner_text()
    assert ui_page.locator(".chip").count() >= 1
    assert ui_page.locator(".statrow").inner_text().count("·") == 2
```

- [ ] **Step 2: Run** (opt-in) — fails: no standby view.

- [ ] **Step 3: Implement** `composer.js` then `standby.js`. Wire
  `store.view === "standby"` → `mount(view, ctx)` in `app.js`.

- [ ] **Step 4: Manual check** against `docs/design/IO Desktop.dc.html` §1a —
  spacing, the stat row, the orb size, the chip pills, the input.

- [ ] **Step 5: Commit**

```bash
git add frontend/views/standby.js frontend/components/composer.js tests/test_frontend_smoke.py
git commit -m "feat(ui): Standby view — greeting, stats, orb, surfaced chips, composer"
```

---

## Task 5: Recorder + Listening view + the voice round-trip

**Files:**
- Create: `frontend/vendor/recorder.js`, `frontend/views/listening.js`
- Test: `tests/test_frontend_recorder.py` (node), `tests/test_frontend_smoke.py`

**Interfaces:**
- Produces:
  - `frontend/vendor/recorder.js` — `export class WavRecorder`:
    `await start()` (getUserMedia → AudioContext → a `ScriptProcessorNode` or
    `AudioWorklet` accumulating `Float32`), `level()` → current RMS `0..1`,
    `await stop()` → a `Blob` of a **16 kHz mono PCM16 WAV** (downsampled from
    the context rate, 44-byte header written in JS). `dispose()`. Pure DSP
    (downsample + WAV encode) is exported as `encodeWav(float32, inRate)` for
    the node test.
  - `frontend/views/listening.js` — `export function mount(root, ctx)`:
    `Orb({mode:"listening"})`, a `LISTENING` kicker, `GAIN / VAD / ELAPSED` mono
    readouts (ELAPSED ticks; GAIN from `recorder.level()`), and the §1b hint
    "Release ⌥ Space to send · Esc to cancel". On entry: `new WavRecorder()`,
    `start()`. `⌥Space` up / a tap on the orb / the mic button → `stop()` →
    `ctx.api.sendVoice(blob, {conversationId, speak: autoSpeak !== "never"})` →
    push the `transcript` as a user turn + the reply as an io turn into
    `store.transcript`, `ctx.goto("conversation")`, and if `audio_b64` and
    `autoSpeak !== "never"` → `ctx.speak(audio_b64)`. `Esc` → cancel, back to the
    previous view. On a `503`/`422` → a one-line inline error, back to Standby.
    Titlebar `#status` = `● MIC LIVE`.
  - `standby.js` mic button and `⌥Space` route here; `app.js` gates entry on
    `store.voiceOk` (from `ctx.api.voiceHealth()` at boot) — if false, the mic
    button is disabled with the `reason` as its `title`.

- [ ] **Step 1: Write the node recorder test** — `tests/test_frontend_recorder.py`

```python
import json, shutil, subprocess
from pathlib import Path
import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_encode_wav_shape():
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = f"""
      import {{ encodeWav }} from {json.dumps(str(FRONTEND / 'vendor' / 'recorder.js'))};
      const n = 48000;                       // 1s at 48k
      const f = new Float32Array(n).fill(0.2);
      const blob = encodeWav(f, 48000);      // -> ArrayBuffer in node shim
      const b = new Uint8Array(blob);
      const rate = b[24] | (b[25]<<8) | (b[26]<<16) | (b[27]<<24);
      if (String.fromCharCode(...b.slice(0,4)) !== 'RIFF') throw 'no RIFF';
      if (rate !== 16000) throw 'rate ' + rate;
      const samples = (b.length - 44) / 2;
      if (Math.abs(samples - 16000) > 2) throw 'samples ' + samples;
      console.log('ok');
    """
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True)
    assert "ok" in r.stdout, r.stderr
```

(`encodeWav` must be written to run headless — take/return typed arrays, no
`AudioContext`. The `WavRecorder` class wraps it with the browser plumbing.)

- [ ] **Step 2: Run** — skips without node, else fails (no `recorder.js`).

- [ ] **Step 3: Implement `recorder.js`** (`encodeWav` pure + `WavRecorder`
  browser class) then `listening.js`. Add the smoke assertions:

```python
def test_listening_enters_and_shows_mic_live(ui_page):
    ui_page.grant_mic()
    ui_page.goto_view("talk")
    assert ui_page.locator("#status").inner_text().strip().endswith("MIC LIVE")
    assert ui_page.locator(".orb[data-mode=listening]").count() == 1
```

- [ ] **Step 4: Manual check** — `.\dev.ps1 up`, download a Piper voice if
  needed, open `/app/`, press the mic, say something, confirm the transcript
  lands, the answer types, and (auto-speak) it plays.

- [ ] **Step 5: Run** — `uv run pytest tests/test_frontend_recorder.py -q` (node
  path) + `uv run pytest tests/test_frontend_assets.py -q`. Commit.

```bash
git add frontend/vendor/recorder.js frontend/views/listening.js tests/test_frontend_recorder.py tests/test_frontend_smoke.py
git commit -m "feat(ui): WavRecorder + Listening view + the /voice round-trip"
```

---

## Task 6: Conversation view — bubbles, markdown, cards, simulated typing

**Files:**
- Create: `frontend/views/conversation.js`, `frontend/components/bubble.js`,
  `frontend/components/card.js`
- Modify: `frontend/vendor/markdown.js` (upgrade), `frontend/typing.js` (new)
- Test: `tests/test_frontend_markdown.py`, `tests/test_frontend_typing.py`,
  `tests/test_frontend_smoke.py`

**Interfaces:**
- Produces:
  - `frontend/vendor/markdown.js` — `renderMarkdown(src)` upgraded to handle:
    `#`/`##`/`###`, `-`/`*`/`1.` lists (nested by indent), `**b**`/`*i*`/`` `c` ``,
    fenced blocks (```mermaid``` → `<pre class="mermaid-src" data-note="diagram">`,
    others → `<pre><code>` with a copy affordance class), blockquotes, a simple
    pipe table, links (non-local hrefs → plain text), paragraphs. HTML-escaped
    first. Pure, no deps.
  - `frontend/typing.js` — `export function revealText(el, text, { cps = 45,
    minThinkMs = 600, onProgress, onDone })`: shows nothing for `minThinkMs`,
    then appends characters at `cps` (accelerating past 240 chars), calling
    `onProgress(soFar)` and `onDone()`. Returns `cancel()` which completes
    instantly. Time via `performance.now()` + `requestAnimationFrame`; a
    `{ now }` injectable clock for the node test.
  - `frontend/components/bubble.js` — `userBubble(text)` → right-aligned
    `#1b1d2b` bubble (§1c); `ioBubble()` → `{ el, body, avatar,
    setStreaming(bool) }` — left, with the 22 px orb-dot avatar and a blinking
    `io-caret` while streaming.
  - `frontend/components/card.js` — `renderCard(card)`:
    - `record` → the §1c/§1d record strip: mono `KIND · DOMAIN · <when>`
      kicker, title (Inter 13–15), entity chips (`entities[]`, person chips take
      the accent outline). Clicking a person/occasion chip → `ctx` event to open
      the inspector for that `EntityRef`.
    - `tasklist` → the §1c bordered list: `circle`/`check-circle` glyph, title,
      a mono `BY <time>` / date / `DONE`.
    - `sources` → the §1c line: `brain` icon + `{count} MEMORIES USED` + the
      `labels` joined with ` · `.
  - `frontend/views/conversation.js` — `mount(root, ctx)`: renders
    `store.transcript` (each item `{role, text, shape, cards, streaming}`) into a
    scrollable column; a compact `Composer({compact:true, placeholder:"Reply to
    IO"})`; the right **inspector** slot (Task 7). On a new assistant turn:
    append an `ioBubble`, `setStreaming(true)`, `revealText(body, text, {cps:
    ctx.store.get().typingCps, minThinkMs: …, onProgress: rerenderMarkdownSoFar,
    onDone: () => { renderMarkdown final; fade in cards; open inspector;
    setStreaming(false) }})`. Sends go over `ctx.ws` (fallback POST). A `gate`
    turn shows the reason + a "yes"/"rephrase" affordance that replies with the
    `pending_token`. Titlebar `#status` = `{recalls} RECALLS · {writes} WRITES`
    for the session.

- [ ] **Step 1: Write the failing pure tests**

`tests/test_frontend_markdown.py` (node): feed a doc with a heading, a nested
list, a table, a fenced `mermaid` block, a `[text](https://evil.com)` link →
assert `<h2>`, `<ul><li>`, `<table>`, `mermaid-src`, and that `evil.com` does
**not** appear in an `href`.

`tests/test_frontend_typing.py` (node): `revealText` with an injected clock;
advance `minThinkMs - 1` → element still empty; advance past it and enough
frames → full text; `cancel()` mid-way → full text immediately.

- [ ] **Step 2: Run** — skip without node, else fail.

- [ ] **Step 3: Implement** `markdown.js` upgrade, `typing.js`, `bubble.js`,
  `card.js`, `conversation.js`. Add the smoke test:

```python
def test_conversation_types_reply_and_renders_card(ui_page):
    ui_page.goto_view("standby")
    ui_page.fill(".composer textarea", "what work do I have today?")
    ui_page.press(".composer textarea", "Enter")
    ui_page.wait_for(".msg.io .io-body")            # typing started
    ui_page.wait_for_done()                          # onDone fired (helper polls a data attr)
    assert ui_page.locator(".card.sources, .card[data-type=sources]").count() == 1
    assert ui_page.locator(".msg.io .io-caret").count() == 0   # streaming ended
```

- [ ] **Step 4: Manual check** against §1c — bubble shapes, the record/tasklist
  cards, the "N MEMORIES USED" line, the typing cadence (feels deliberate, holds
  ~600 ms before the first character), `Esc` completes instantly.

- [ ] **Step 5: Run + commit**

```bash
git add frontend/ tests/test_frontend_markdown.py tests/test_frontend_typing.py tests/test_frontend_smoke.py
git commit -m "feat(ui): Conversation view — bubbles, upgraded markdown, cards, simulated typing"
```

---

## Task 7: Memory Inspector panel

**Files:**
- Create: `frontend/components/inspector.js`
- Modify: `frontend/views/conversation.js` (mount the slot)
- Test: `tests/test_frontend_smoke.py`

**Interfaces:**
- Produces:
  - `frontend/components/inspector.js` — `export function mountInspector(root,
    panel)` builds the §1c right panel from the `GET /entity/{etype}/{id}`
    payload: `MEMORY INSPECTOR` kicker, an avatar (initials in an accent-ring
    circle) + `name` + `subtitle`, a faded rule, then each `fact` as
    `{ label kicker, text }`, a spacer, the `CONFIDENCE` bar
    (`--color-accent-600` fill at `confidence * 100%`) + `{pct}% · SOURCED FROM
    {sourced_from} NOTES`, and an outlined "Open {name}'s file" button (inert —
    `title="coming soon"`). `export function clearInspector(root)`.
  - `conversation.js` — after an assistant turn's `onDone`, if the top `record`
    card has `entities.length`, `ctx.api.entity(entities[0].etype,
    entities[0].id)` → `mountInspector(rightSlot, panel)` with a slide-in; a
    click on an entity chip re-targets it. The slot is hidden (width 0) when
    empty; the main column widens to fill.

- [ ] **Step 1: Smoke assertion**

```python
def test_inspector_appears_for_entity_reply(ui_page):
    # the stub /entity/person/1 returns Priya's panel; the stub /utterance reply
    # carries a record card with entities:[{etype:"person",id:1,name:"Priya"}]
    ui_page.send("remind me what Priya's into")
    ui_page.wait_for_done()
    assert ui_page.locator(".inspector").is_visible()
    assert "SOURCED FROM" in ui_page.locator(".inspector").inner_text()
```

- [ ] **Step 2: Run** (opt-in) — fails.

- [ ] **Step 3: Implement** `inspector.js` + the `conversation.js` wiring +
  panel CSS (borrow §1c measurements).

- [ ] **Step 4: Manual check** against §1c right panel.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/inspector.js frontend/views/conversation.js frontend/app.css tests/test_frontend_smoke.py
git commit -m "feat(ui): Memory Inspector panel"
```

---

## Task 8: Sidebar — conversations list, new conversation, history load

**Files:**
- Modify: `frontend/index.html` (a collapsible conversations drawer or a rail
  sub-panel), `frontend/app.js`, `frontend/app.css`
- Test: `tests/test_frontend_smoke.py`

**Interfaces:**
- Produces:
  - A conversations list reachable from the rail (`chat-teardrop-dots` opens it):
    grouped `Today` / `Yesterday` / `Earlier` from `ctx.api.conversations()`,
    each row the `title`; the active one takes the accent left-border (§1c rail
    grouping style). A `+ New conversation` control → `ctx.api.newConversation()`
    → `store.set({ conversationId, transcript: [], view: "standby" })`.
  - Selecting a conversation → `ctx.api.conversation(id)` → hydrate
    `store.transcript` from `messages` (oldest first; assistant messages
    rendered without re-typing — instant), `view: "conversation"`.
  - On boot, `app.js` calls `ctx.api.conversations()`; if one exists it becomes
    `store.conversationId` and Standby shows a "Continue" affordance, else a
    fresh conversation is implied on first send.

- [ ] **Step 1: Smoke assertion**

```python
def test_new_conversation_clears_transcript(ui_page):
    ui_page.send("hello")
    ui_page.wait_for_done()
    ui_page.click(".rail [data-nav=conversation]")
    ui_page.click("text=New conversation")
    assert ui_page.locator(".msg").count() == 0
```

- [ ] **Step 2: Run** (opt-in) — fails.

- [ ] **Step 3: Implement.** Keep it a lightweight drawer, not a permanent
  column — Standby stays uncluttered.

- [ ] **Step 4: Manual check.**

- [ ] **Step 5: Commit**

```bash
git add frontend/ tests/test_frontend_smoke.py
git commit -m "feat(ui): conversations drawer — list, new, history hydration"
```

---

## Task 9: Desktop shell — fullscreen, window geometry, native menu

**Files:**
- Modify: `io_assistant/service/runner.py`, `io_assistant/cli.py`,
  `io_assistant/config.py` (already has `UiConfig` from Plan 5 Task 9)
- Test: `tests/test_cli_serve.py` (unchanged assertions hold), manual

**Interfaces:**
- Produces:
  - `runner.open_window(url, *, fullscreen, geometry_path)` —
    `webview.create_window("IO", url, fullscreen=fullscreen, text_select=True,
    width/height from geometry_path or 1180×760, min_size=(960, 640))`; on
    close, write the final size/pos to `geometry_path`
    (`~/.local/share/io/window.json`). A native menu:
    `File → New Conversation` (posts to `/conversation` then reloads),
    `View → Reload` / `Toggle Fullscreen` (F11), `Edit → Cut/Copy/Paste`.
  - `cli.run()` passes `fullscreen=load_config().ui.fullscreen` and the geometry
    path. `dev.ps1 up -Window` is unchanged (it calls `io run`).

- [ ] **Step 1** — no new automated test (pywebview windows aren't headless-testable
  here); `tests/test_cli_serve.py` must still pass.

- [ ] **Step 2: Implement** `open_window` + the menu + geometry persistence.

- [ ] **Step 3: Manual check** — `.\dev.ps1 up -Window`: opens fullscreen, F11
  toggles, close → reopen restores size; the menu items work.

- [ ] **Step 4: Run** `uv run pytest tests/test_cli_serve.py -q` → PASS. Commit.

```bash
git add io_assistant/service/runner.py io_assistant/cli.py
git commit -m "feat: fullscreen window, remembered geometry, native menu"
```

---

## Task 10: Assets lint, DOM-smoke harness, docs, state

**Files:**
- Modify: `tests/conftest.py` (finalise `ui_page`), `.claude/knowledge/desktop-app.md`,
  `.claude/skills/run-local.md`, `pyproject.toml` (add the `ui` marker),
  `.claude/state/*`
- Test: run everything

**Interfaces:**
- Produces:
  - `pyproject.toml` `[tool.pytest.ini_options].markers` += `"ui: Playwright DOM
    smoke (set IO_UI_TESTS=1; needs `uv run playwright install chromium`)"`.
  - The `ui_page` fixture (in `conftest.py`, import-guarded): a stub server that
    serves `frontend/` **and** answers `GET /standby`, `GET /voice/health`,
    `GET /conversations`, `GET /conversation`, `POST /conversation`,
    `GET /entity/{…}`, `POST /utterance`, `POST /voice`, `WS /ws` with canned
    fixtures (`tests/fixtures/ui/*.json`); Playwright Chromium headless; helpers
    `goto_view`, `send`, `fill`, `press`, `click`, `wait_for`, `wait_for_done`,
    `grant_mic`, `eval`.
  - `desktop-app.md` — the frontend map (`frontend/` file roles, the state
    store, the API client, the orb modes, the three views, typing/pacing), the
    vendoring rule, and `IO_UI_TESTS=1` for the smoke.
  - `run-local.md` — `uv run playwright install chromium` as the one-time step
    for `IO_UI_TESTS=1 uv run pytest -m ui`.

- [ ] **Step 1: Finalise the `ui_page` fixture** and its canned fixtures.

- [ ] **Step 2: Full suite (no UI)** — `.\dev.ps1 test -q` → PASS, incl. the
  asset lint, the node pure-logic tests (when node present), and
  `tests/test_e2e_store.py`'s socket guard.

- [ ] **Step 3: UI smoke (opt-in)** — `uv run playwright install chromium` then
  `IO_UI_TESTS=1 uv run pytest -m ui -q`. Record the result in the commit
  message; if Playwright/Chromium won't install in this environment, note that
  and rely on the manual checks from Tasks 3–8.

- [ ] **Step 4: Docs + state.** Move Plan 6 to `completed.md` (dated). Update
  `session.md`. Backlog reminder: state 1d task runner, external-source
  provenance, entity-file browser, `/ws` token streaming, Kokoro.

- [ ] **Step 5: Commit**

```bash
git add tests/ .claude/ pyproject.toml
git commit -m "test+docs: UI smoke harness (opt-in), frontend docs; Plan 6 complete"
```

---

## Self-Review

**Spec coverage (Phase 1.5 §2, §7):**
- §2 Nocturne vendoring (fonts, icons, tokens, no CDN) → Task 1 + the asset
  lint. §2 accent-as-line, fade-at-ends, themed states → carried in `app.css`,
  checked against `docs/design/`.
- §7.1 shell (window, rail, status) → Task 2 + Task 9. §7.2 orb (4 modes) →
  Task 3. §7.3 Standby → Task 4; Listening → Task 5; Conversation + Inspector →
  Tasks 6 + 7. §7.4 pacing (`min_think_ms`, `typing_cps`, caret, `Esc`) →
  Task 6 `typing.js`. §7.5 `[ui]` config → consumed (Plan 5 defined it).
  §7.6 desktop shell (`fullscreen`, geometry, menu) → Task 9.
- Conversations drawer / history → Task 8 (spec §3.5 `/conversation(s)` client).

**Local-first check:** Task 1 vendors every asset; `tests/test_frontend_assets.py`
fails on any external `http(s)://` or `@import url(http`; the markdown renderer
drops non-local link hrefs; the app only ever calls `127.0.0.1`.

**Placeholder scan:** the pasted CSS is deliberately deferred to
`docs/design/nocturne/styles.css` + `docs/design/IO Desktop.dc.html` (named as
the source of truth in the Global Constraints) rather than duplicated — every
task names the exact mockup section to match. All JS interfaces are specified
with signatures and behaviour; the node/Playwright test bodies are literal.

**Type / contract consistency:**
- `ctx = { store, api, ws, speak, goto }` — Task 2 def, every view uses it.
- `store` shape (`view, conversationId, transcript, busy, autoSpeak, voiceOk,
  connection, typingCps`) — Task 2 def, Tasks 4–8 read/patch it.
- `Api` method set (`standby, voiceHealth, sendText, sendVoice, conversation,
  conversations, newConversation, entity, connectWs`) — Task 2 def, matches the
  Phase 5 endpoints exactly (`/standby`, `/voice/health`, `/utterance`,
  `/voice`, `/conversation`, `/conversations`, `/conversation` POST,
  `/entity/{etype}/{id}`, `/ws`).
- `Orb` returns `{ setMode, setLevel, destroy }` — Task 3 def, `app.js`
  (`speaking` amplitude) and views use it.
- `revealText(el, text, opts) -> cancel` — Task 6 def, `conversation.js` uses it.
- `renderCard(card)` handles `card.type ∈ {record, tasklist, sources}` — matches
  Plan 5's `Card` union and `model_dump(mode="json")` output.
- `TurnResponse` / `VoiceOut` fields consumed by `api.js` match Plan 5 Task 5/6.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between.
   Order 1 → 10; Task 2 needs 1; Tasks 4–8 need 2 + 3; Task 6 before 7; Task 9
   independent after 2.
2. **Inline Execution** — `superpowers:executing-plans`, batched with checkpoints.

**Verification note:** the asset lint and the `node` pure-logic tests
(`markdown.js`, `typing.js`, `recorder.js`'s `encodeWav`) run in normal CI when
`node` is on PATH. The Playwright DOM smoke is opt-in (`IO_UI_TESTS=1` +
`playwright install chromium`); where it can't run, Tasks 3–8 each carry a
manual check against `docs/design/IO Desktop.dc.html`.
