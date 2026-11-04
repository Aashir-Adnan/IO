# IO

A local-first, single-user AI assistant. You talk or type to it; it remembers people, places, items and things that happened or need doing, and answers questions about them later. It runs on your machine, stores its data in a Postgres database you own, and only ever calls out to a third party if you explicitly opt into one.

<!-- SCREENSHOT: drop a window capture of the standby view (orb + clock + agenda) here, e.g. ![IO](docs/screenshot.png) -->

## What it does

- **Capture** whatever you say or type — a hotkey + mic, or the text composer.
- **Route** it: is this something to remember (store), a question (query), or neither (unknown)?
- **Store**: extract people/places/items/occasions and a free-form `record` (an event, task, chore, note — anything), resolve them against what it already knows, ask for confirmation when it's unsure, then persist in one transaction.
- **Query**: plan what to retrieve, pull it from Postgres with structured SQL and vector search, merge/rank/expand recurring events, then phrase an answer.
- Everything above also runs through a FastAPI service with a desktop window (PyWebView) on top, so it has a normal chat UI, a memory browser, a file library, home-screen widgets and voice in and out.

## The LLM-vs-Python boundary

The model (local Ollama or Anthropic) is used for exactly four things: **route**, **extract**, **plan**, **phrase**. It never writes SQL, never does date arithmetic, never decides whether two mentions of "Sarah" are the same person, never filters or ranks results. All of that — identity resolution, date grounding, SQL, filtering, ranking — is deterministic Python. That split is what makes it safe to swap a weaker/cheaper model in: it extracts worse, but it structurally cannot corrupt the data.

## Features

- **Memory**: an open-ended `records` table (events, tasks, chores, notes — any `kind` the model coins, no schema change needed) plus `people` / `places` / `items` / `occasions`, each with aliases and a vector embedding for semantic recall.
- **File index**: opt-in, points at folders you register (`~/Documents`, `~/Pictures`, …), indexes text and media with embeddings + full-text search, so you can ask questions about your own files.
- **Voice**: `faster-whisper` for speech-to-text (batch or real-time streaming), Piper for text-to-speech — both local by default; an optional cloud STT (Soniox) is there if you want lower latency and are fine with that audio leaving the machine.
- **Desktop app**: a FastAPI service plus a PyWebView window — chat, a memory browser, a file library with folders/thumbnails, home-screen widgets (agenda, weather, clock), conversation history. Packages into a standalone Windows `.exe` with PyInstaller.
- **Phone app** (`phone/`, Flutter, Android first): a standalone client with its own on-device SQLite store that talks to Anthropic directly — no desktop required — plus optional sync back to your desktop's memory over your own network.
- **Sync**: optional, opt-in sync of your memory through your own Google Drive (or a plain folder), so the phone and desktop stay consistent.

## Stack

- Python 3.11+, managed with [`uv`](https://docs.astral.sh/uv/).
- **Postgres 16 + pgvector** for storage and vector search; **Alembic** for every schema change (no ad-hoc `ALTER`).
- **FastAPI** + **uvicorn** service, **PyWebView** desktop window, a vendored vanilla-JS frontend (no build step, no CDN).
- **Ollama** (local models) by default; **Anthropic** (`claude-haiku-4-5` / `claude-sonnet-5`) as an opt-in backend, or a hybrid of the two.
- **faster-whisper** (STT) + **Piper** (TTS) for voice, both local.
- **Flutter** for the Android phone app.
- Docker Desktop for the bundled Postgres container (the one hard prerequisite for the packaged `.exe`).

## Running it

```powershell
.\dev.ps1 up          # start Postgres + Ollama check + migrate + the service, and open the desktop window
                       # closing the window shuts the whole stack down
.\dev.ps1 up -NoWindow # or: .\dev.ps1 serve   — headless, for tests/background use
.\dev.ps1 down         # stop everything
.\dev.ps1 status       # what's running
.\dev.ps1 logs         # tail the service log
.\dev.ps1 doctor       # environment / model checks
```

IO is desktop-only — it never opens in a browser; running it again just brings the existing window to the front. Configuration lives in `config.toml` (backend provider, voice, files, web answers, sync — all documented inline); secrets go in a `.env` you create from `.env.example` (never committed).

## Testing

```powershell
.\dev.ps1 test           # runs `uv run pytest` against a separate io_test database
```

TDD throughout; the database is never mocked — tests run against a real Postgres named by `IO_TEST_DATABASE_URL`. Some suites are opt-in and skip by default unless you set the matching env var: `IO_OLLAMA_TESTS`, `IO_ANTHROPIC_TESTS`, `IO_VOICE_TESTS`, `IO_BUILTIN_EMBED_TESTS`, `IO_UI_TESTS` (Playwright). The phone app has its own suite: `flutter analyze && flutter test` in `phone/`, no device needed.

## Privacy

IO is local-first by design: no telemetry, no analytics, no CDN assets, no bundled cloud calls. The only network call IO makes on your behalf without you opting in further is `git fetch` against its own update remote (to check for a newer version — never applies anything automatically). Everything else requires you to turn it on:

- Cloud model calls to `api.anthropic.com`, only when `backend.provider` is `"anthropic"` or `"hybrid"`, using your own API key from the environment — IO never stores it.
- Cloud speech-to-text (Soniox), only if you set a Soniox key and provider.
- A self-hosted SearXNG for opt-in web answers (runs in IO's own Docker stack, so queries never leave your machine) or an opt-in cloud search provider.
- Memory sync through your own Google Drive or a local folder, only if you turn sync on.
- A weather widget and a Gmail "Important" widget, only if you add them, and only metadata in Gmail's case (never message bodies).
- Reachability from your own phone, only if you set a remote access token and point it at your own network (e.g. Tailscale).

Embeddings and the datastore itself are always local, regardless of backend.

`.env` is git-ignored (and was never committed — checked the full history) — copy `.env.example` and fill in your own values.
