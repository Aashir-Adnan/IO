# Conventions

- **Package name is `io_assistant`** — never `io` (stdlib clash). The CLI
  command is `io` (`[project.scripts] io = "io_assistant.cli:app"`, Typer).
- **Everything runs through `uv run`** — `uv run pytest`, `uv run alembic`,
  `uv run io ...`. Python 3.11+, `uv` for env and dependencies.
- **TDD always** — failing test first, watch it fail, minimal implementation,
  watch it pass, commit. See `rules/test-discipline.md`.
- **Never mock the database** — tests run against the real PostgreSQL named by
  `IO_TEST_DATABASE_URL` (database `io_test`). Backend model calls may be faked
  via a `FakeBackend` test double; persistence, resolver, and SQL layers never
  are.
- **One `config.toml`** for all settings; `.env` only for the database URL and
  (if used) the Anthropic credential.
- **Pytest markers `ollama` and `anthropic` are opt-in** — collected only when
  `IO_OLLAMA_TESTS=1` / `IO_ANTHROPIC_TESTS=1` respectively; default CI runs
  against a stub backend.
- **Schema changes are Alembic migrations only** (`rules/migrations.md`); no
  ad-hoc `ALTER`.
- **Repo layout** — one package per layer (`capture/`, `transcribe/`, `route/`,
  `extract/`, `resolve/`, `persist/`, `query/`, `respond/`, `backend/`,
  `service/`), `orchestrator.py`, `db/` (models + `migrations/`), `prompts/`
  (versioned), `frontend/` (vendored static assets).
- **The service binds `127.0.0.1` only**; the frontend references no external
  URLs — `tests/test_frontend_assets.py` enforces it. `io run` opens the
  pywebview window; `io serve` is headless (the client for the Plan 4 voice
  loop). See `knowledge/desktop-app.md`.
