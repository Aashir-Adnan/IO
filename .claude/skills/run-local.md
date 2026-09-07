# Skill: run IO locally

Windows PowerShell 5.1 (no `pwsh`). Run from repo root. In a bash shell `uv` may
need `export PATH="$HOME/.local/bin:$PATH"` first.

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
uv run io repl
```

## Ollama resource env vars

Set on the Ollama process (not IO): `OLLAMA_MAX_LOADED_MODELS=1`,
`OLLAMA_NUM_PARALLEL=1` — IO never runs two models concurrently. See
`rules/resource-budget.md`.
