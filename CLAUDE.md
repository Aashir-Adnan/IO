# IO

Local-first, single-user AI assistant. See docs/superpowers/specs/2026-09-07-io-phase-1-design.md.

## First, every session

Read `.claude/state/session.md` to see what's in progress and which knowledge
files and skills are relevant.

## Prime directive

**Local-first.** IO runs on the user's machine. The only sanctioned non-local
network call is the opt-in Anthropic backend (`backend.provider` = "anthropic" or
"hybrid" in config.toml). Everything else stays local — no telemetry, no
analytics, no CDN assets, no bundled cloud calls. Any other outbound connection
to a non-local host is a bug.

## Memory scaffold

- `.claude/knowledge/` — architecture, data model, extraction, query pipeline,
  local stack, model backends, conventions. Read the relevant file before working
  in that area.
- `.claude/rules/` — ENFORCED. local-first, llm-boundaries, test-discipline,
  migrations, resource-budget. These override default behavior.
- `.claude/skills/` — add-entity-type, add-query-capability, run-local.
- `.claude/state/` — backlog.md, completed.md, session.md. Update session.md when
  you start something; move finished items from backlog.md to completed.md (dated,
  newest first) at the end of a session with meaningful work.

## Conventions

- Package: `io_assistant` (never `io` — stdlib clash). CLI command: `io`.
- Everything runs through `uv run` (`uv run pytest`, `uv run alembic`, `uv run io`).
- TDD always. Never mock the database.
- Data model: one open-ended `records` table (`kind` / `domain` slugs coined by
  the model) plus entity tables `people`/`places`/`items`/`occasions`. New life
  domains are new `kind`/`domain` values, never a new table. Schema changes are
  Alembic migrations only.
