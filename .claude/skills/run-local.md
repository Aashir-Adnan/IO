# Skill: run IO locally

Windows PowerShell 5.1 (no `pwsh`). Run from repo root. In a bash shell `uv` may
need `export PATH="$HOME/.local/bin:$PATH"` first.

## The one command: `dev.ps1`

`dev.ps1` at the repo root is the single on/off switch — it manages Docker
Postgres, checks/starts Ollama, migrates, and runs the `io` service.

```
.\dev.ps1 up          # Postgres + Ollama + migrate + io service (background)
.\dev.ps1 up -Window  #  ... open the desktop window; closing it shuts the stack down
.\dev.ps1 install     # put a Desktop "IO" shortcut = double-click to launch, close window to stop
.\dev.ps1 app         # open the UI (http://localhost:8765/app/) in a browser
.\dev.ps1 listen      # voice mode
.\dev.ps1 status      # what's running
.\dev.ps1 logs        # tail the service log
.\dev.ps1 test [...]  # run the suite against io_test (brings Postgres up first)
.\dev.ps1 doctor      # io doctor
.\dev.ps1 down        # stop the service + Postgres (data kept)
.\dev.ps1 down -Wipe  # ... and delete the DB volume
```

Runtime state (service PID + logs) lives in `.io-dev/` (gitignored). Ollama is
left running by `down` (it's a shared service). Credentials come from `.env`
(`ANTHROPIC_AUTH_TOKEN` for the cloud backend; not needed for
`[backend].provider = "local"`).

The manual steps below are what `dev.ps1` automates.

## One-time setup

`scripts/setup.ps1` does all of this
(`powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`). Prerequisites
installed by hand first: Docker Desktop (must be RUNNING) and Ollama.

The steps it runs:

```
# 1. uv (if missing)
irm https://astral.sh/uv/install.ps1 | iex        # then add $HOME\.local\bin to PATH

# 2. Ollama models
ollama pull llama3.2:3b
ollama pull nomic-embed-text

# 3. PostgreSQL 16 + pgvector via Docker (databases io and io_test, user/pw io/io, :5432)
docker compose up -d

# 4. enable pgvector in both databases
docker compose exec -T db psql -U io -d io      -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker compose exec -T db psql -U io -d io_test -c "CREATE EXTENSION IF NOT EXISTS vector;"

# 5. .env
Copy-Item .env.example .env       # if missing
```

## Verify the environment

```
powershell -ExecutionPolicy Bypass -File scripts\check-env.ps1
```
Checks: `uv` on PATH, Docker daemon, Ollama reachable (http://localhost:11434),
both models pulled, both databases reachable, pgvector present in both.

## Migrate and run

```
uv run alembic upgrade head
uv run io repl                 # typed REPL
uv run io serve                # local FastAPI service (127.0.0.1:8765)
uv run io run                  # service + desktop window (/app)
```

## Voice (Plan 4)

```
# one-time: download the default Piper voice (natural female US English)
uv run python -m piper.download_voices en_US-hfc_female-medium --data-dir $HOME\.local\share\io\piper

uv run io serve                # in one shell
uv run io listen               # in another — hotkey to talk, hear the answer
uv run io listen --passive     # hands-free VAD mode
```

## Frontend DOM smoke (opt-in)

```
uv run playwright install chromium          # one-time
$env:IO_UI_TESTS=1; uv run pytest -m ui -q   # Playwright headless against a stub server
```
Skips cleanly when `IO_UI_TESTS` is unset or playwright/chromium are absent.
Pure-JS frontend tests (markdown/typing/recorder) run in the normal suite via
`node` when it's on PATH.

## Files (Phase 2A)

Opt-in. In `config.toml`:
```
[files]
enabled = true
allowlist_roots = ["~/Documents", "~/Downloads"]
```
Then:
```
uv run io files add "C:\Users\me\Documents\Taxes"   # register + index
uv run io files search what does my lease say about pets
uv run io files list ; uv run io files status
```
Or by voice/text through the assistant: *"remember my Taxes folder"*,
*"what does my lease say about pets"*. **Note:** when `[backend].provider` is
not `local`, file text is sent to `api.anthropic.com` (embeddings stay local).

## Go / no-go

```
uv run io doctor
```
Checks Postgres, pgvector, the backend (Ollama model or Anthropic credential),
embeddings, faster-whisper, Piper + the voice model file, and VRAM headroom.
Exit 0 only when everything the current config needs is present.

## Ollama resource env vars

Set on the Ollama process (not IO): `OLLAMA_MAX_LOADED_MODELS=1`,
`OLLAMA_NUM_PARALLEL=1` — IO never runs two models concurrently. See
`rules/resource-budget.md`.
