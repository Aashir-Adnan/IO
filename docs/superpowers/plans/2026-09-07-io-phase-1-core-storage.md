# IO Phase 1 — Core Storage Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local CLI that takes a typed sentence like "I went out with Nafay to eat at Arcadian for his and Eelian's birthday" and stores it as normalized, linked rows (event, people, place, occasion) in PostgreSQL, with every raw utterance logged verbatim.

**Architecture:** A layered pipeline — Route → Extract → Resolve → Persist — where every LLM call goes through a `Backend` interface (local Ollama by default, Anthropic or hybrid as opt-in) and all logic (dedup, date grounding, linking) is deterministic Python. Embeddings are always generated locally so the pgvector space is stable regardless of backend.

**Tech Stack:** Python 3.11+, `uv`, SQLAlchemy 2.x + Alembic, `psycopg` 3, `pgvector`, `pydantic` v2 + `pydantic-settings`, `httpx`, `anthropic` SDK, `rapidfuzz`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-07-io-phase-1-design.md` (read §1–4, §8, §10, §13 before starting)

**Task 0 sets up the local environment** (PostgreSQL + pgvector via Docker, Ollama, `uv`) and must complete — `pwsh scripts/check-env.ps1` green — before Task 1.

## Global Constraints

- **Python** ≥ 3.11 (uses stdlib `tomllib`). Dependency management via `uv`.
- **Local-first:** no outbound network except (a) `localhost` for Postgres and Ollama, and (b) `api.anthropic.com` *only* when `backend.provider` is `"anthropic"` or `"hybrid"`. No telemetry, no analytics, no CDN.
- **LLM boundary:** the model is used only for `route`, `extract`, `plan`, `phrase`. It never emits SQL, never does date arithmetic, never filters or ranks. All of that is deterministic Python.
- **Embeddings are always local** via Ollama `nomic-embed-text`, regardless of backend. Embedding dimension is fixed in config (`768` for `nomic-embed-text`); changing it is a migration + backfill.
- **Migrations:** every schema change is an Alembic migration. No ad-hoc `ALTER`.
- **TDD:** write the failing test first, watch it fail, implement minimally, watch it pass, commit. Never mock the database — tests run against a real disposable PostgreSQL.
- **Config:** one `config.toml` at repo root. Secrets (DB URL if the user prefers, Anthropic key) come from environment / `.env`, never committed.
- **Naming:** the Python package is `io_assistant` (the name `io` collides with the stdlib module — do not use it as the package name). The CLI command is `io`.

---

## File Structure

```
io_assistant/
  __init__.py
  config.py              # load + validate config.toml, env overrides
  cli.py                 # `io` entrypoint (store / repl / doctor stub)
  models_domain.py       # Pydantic domain types: Utterance, Intent, ExtractionResult, ...
  db/
    __init__.py
    base.py              # SQLAlchemy engine/session factory
    models.py            # ORM: Utterance, Person, Place, Item, Event, Task, Occasion, link tables
    migrations/          # Alembic env + versions
  backend/
    __init__.py
    interface.py         # Backend Protocol + shared prompt-rendering helpers
    local.py             # LocalBackend (Ollama via httpx)
    anthropic_backend.py  # AnthropicBackend
    hybrid.py            # HybridBackend
    factory.py           # build_backend(config) -> Backend
    embed.py             # embed(texts) -> list[list[float]]  (always Ollama)
  prompts/
    route.txt
    extract.txt
  route/
    __init__.py
    router.py            # Router: utterance -> Intent
  extract/
    __init__.py
    schema.py            # the JSON schema string + few-shot examples
    extractor.py         # Extractor: utterance -> ExtractionResult (validate + retry)
  resolve/
    __init__.py
    resolver.py          # EntityResolver: exact -> fuzzy -> vector -> new; confirmation gate
    dates.py             # ground_dates(): relative time expressions -> datetimes
  persist/
    __init__.py
    writer.py            # persist_store(): one transaction, entities + event/task + links + embeddings
  orchestrator.py        # handle_utterance(): Route -> Extract -> Resolve -> Persist
config.toml
pyproject.toml
alembic.ini
.env.example
tests/
  conftest.py           # test DB fixture, config fixture, fake backend
  test_config.py
  test_db_models.py
  test_backend_interface.py
  test_backend_local.py
  test_backend_anthropic.py
  test_backend_factory.py
  test_embed.py
  test_persist.py
  test_resolve.py
  test_dates.py
  test_extract_schema.py
  test_extractor.py
  test_router.py
  test_orchestrator_store.py
  test_e2e_store.py
  fixtures/
    utterances_store.json    # labelled STORE utterances -> expected extraction
    utterances_route.json    # labelled utterances -> expected intent
.claude/
  knowledge/  rules/  skills/  state/
CLAUDE.md
```

---

## Task 0: Local environment setup (PostgreSQL + pgvector + Ollama + uv)

**Files:**
- Create: `docker-compose.yml`, `scripts/setup.ps1`, `scripts/check-env.ps1`
- Modify: `.claude/skills/run-local.md` is created in Task 2 — this task's commands are its source of truth, so keep them in sync.
- Test: `scripts/check-env.ps1` is the verification (no pytest here).

**Interfaces:**
- Consumes: nothing.
- Produces: a running PostgreSQL 16 with `pgvector` on `localhost:5432` (databases `io` and `io_test`), a running Ollama on `localhost:11434` with `llama3.2:3b` and `nomic-embed-text` pulled, `uv` on PATH, and a `.env` file. `scripts/check-env.ps1` exits 0 only when all of that is true.

Platform: Windows 11 + PowerShell. PostgreSQL runs in Docker (cleanest way to get `pgvector` on Windows); Ollama runs natively (it ships a Windows installer and needs GPU access). If the user does not want Docker, a native-PostgreSQL fallback is documented in Step 6.

- [ ] **Step 1: Install `uv`** (if missing)

Run (PowerShell):
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```
Verify: `uv --version`

- [ ] **Step 2: Install Ollama** (if missing)

Download and run the installer from `https://ollama.com/download/windows` (this is a user action — do not script a silent download). After install, Ollama runs as a background service.
Verify: `ollama --version` and `curl http://localhost:11434/api/version`

- [ ] **Step 3: Pull the models**

Run:
```powershell
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```
Verify: `ollama list` shows both.

- [ ] **Step 4: Create `docker-compose.yml`** (PostgreSQL + pgvector)

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: io
      POSTGRES_PASSWORD: io
      POSTGRES_DB: io
    ports:
      - "5432:5432"
    volumes:
      - io_pgdata:/var/lib/postgresql/data
      - ./scripts/initdb:/docker-entrypoint-initdb.d
volumes:
  io_pgdata:
```

Create `scripts/initdb/01-create-test-db.sql`:
```sql
CREATE DATABASE io_test OWNER io;
```

- [ ] **Step 5: Start PostgreSQL and enable the extension**

Run:
```powershell
docker compose up -d
# wait for readiness, then enable pgvector in both databases
docker compose exec -T db psql -U io -d io      -c "CREATE EXTENSION IF NOT EXISTS vector;"
docker compose exec -T db psql -U io -d io_test -c "CREATE EXTENSION IF NOT EXISTS vector;"
```
Verify: `docker compose exec -T db psql -U io -d io -c "\dx"` lists `vector`.

- [ ] **Step 6: Native-PostgreSQL fallback (only if not using Docker)**

Document in `run-local.md`, do not execute unless the user asks:
1. Install PostgreSQL 16 from the EDB installer.
2. Install pgvector: easiest is `nix`/prebuilt — on Windows, install via the
   `pgvector` release DLL matching PG16, copied into `lib/` and
   `share/extension/`, or build with MSVC per the pgvector README.
3. `createdb -U postgres io` and `createdb -U postgres io_test`; create role
   `io` with password `io`; `CREATE EXTENSION vector;` in each DB.

- [ ] **Step 7: Create `.env`**

Run:
```powershell
Copy-Item .env.example .env
```
(`.env.example` is created in Task 1 — if doing Task 0 first, create `.env` directly with the two `IO_*` URLs from the Testing Setup section below.)

- [ ] **Step 8: Create `scripts/check-env.ps1`**

```powershell
$ErrorActionPreference = "Stop"
$ok = $true

function Check($name, $script) {
  try { & $script; Write-Host "OK   $name" -ForegroundColor Green }
  catch { Write-Host "FAIL $name -- $_" -ForegroundColor Red; $script:ok = $false }
}

Check "uv on PATH"            { uv --version | Out-Null }
Check "Ollama reachable"      { (Invoke-WebRequest http://localhost:11434/api/version -UseBasicParsing).StatusCode -eq 200 | Out-Null }
Check "model llama3.2:3b"     { if (-not (ollama list | Select-String "llama3.2:3b")) { throw "not pulled" } }
Check "model nomic-embed-text" { if (-not (ollama list | Select-String "nomic-embed-text")) { throw "not pulled" } }
Check "Postgres io reachable" { docker compose exec -T db psql -U io -d io -c "SELECT 1" | Out-Null }
Check "Postgres io_test"      { docker compose exec -T db psql -U io -d io_test -c "SELECT 1" | Out-Null }
Check "pgvector in io"        { if (-not (docker compose exec -T db psql -U io -d io -c "\dx" | Select-String "vector")) { throw "extension missing" } }
Check "pgvector in io_test"   { if (-not (docker compose exec -T db psql -U io -d io_test -c "\dx" | Select-String "vector")) { throw "extension missing" } }

if (-not $ok) { exit 1 }
Write-Host "`nEnvironment ready." -ForegroundColor Green
```

- [ ] **Step 9: Run the check**

Run: `pwsh scripts/check-env.ps1`
Expected: every line `OK`, final "Environment ready."

- [ ] **Step 10: Commit**

```bash
git add docker-compose.yml scripts/
git commit -m "chore: local environment setup (Postgres+pgvector via Docker, Ollama, uv)"
```

---

## Testing Setup (read before Task 1)

Tests need a real PostgreSQL with the `pgvector` extension. The executor must have one available locally.

- Connection string comes from env var `IO_TEST_DATABASE_URL`
  (e.g. `postgresql+psycopg://io:io@localhost:5432/io_test`).
- `tests/conftest.py` creates all tables from the ORM metadata at the start of a
  test session and drops them at the end; each test runs in a transaction that is
  rolled back (function-scoped fixture).
- If `IO_TEST_DATABASE_URL` is unset, DB-touching tests are **skipped with a clear
  message**, not failed — but the plan assumes it is set.
- Ollama-touching tests (`test_backend_local`, `test_embed`, `test_extractor` real
  path) are marked `@pytest.mark.ollama` and skipped unless `IO_OLLAMA_TESTS=1`.
- Anthropic-touching tests are marked `@pytest.mark.anthropic` and skipped unless
  `ANTHROPIC_API_KEY` is set and `IO_ANTHROPIC_TESTS=1`.

---

## Task 1: Project scaffold + config loader

**Files:**
- Create: `pyproject.toml`, `io_assistant/__init__.py`, `io_assistant/config.py`, `config.toml`, `.env.example`
- Test: `tests/test_config.py`, `tests/conftest.py` (partial — config fixture only)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `io_assistant.config.Config` — a pydantic `BaseSettings` model with nested
    sections: `Config.database_url: str`, `Config.embedding_dim: int`,
    `Config.backend: BackendConfig`, `Config.resolver: ResolverConfig`.
  - `BackendConfig`: `provider: Literal["local","anthropic","hybrid"]`,
    `profile: Literal["light","quality"]`, `anthropic_model: str`,
    `ollama_url: str`, `ollama_keep_alive: str`, `instruct_model: str`,
    `embed_model: str`, `num_thread: int | None`.
  - `ResolverConfig`: `fuzzy_threshold: int` (default 92),
    `vector_similarity_threshold: float` (default 0.85),
    `confidence_gate_threshold: float` (default 0.6).
  - `io_assistant.config.load_config(path: str | Path | None = None) -> Config`
    — reads `config.toml` (default: repo-root `config.toml`), applies env overrides
    (`IO_DATABASE_URL`, `ANTHROPIC_API_KEY` handled by the anthropic backend
    directly, not here), returns a validated `Config`. Raises `ConfigError` on
    invalid/missing required values.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "io-assistant"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "sqlalchemy>=2.0",
    "alembic>=1.13",
    "psycopg[binary]>=3.1",
    "pgvector>=0.2.5",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "httpx>=0.27",
    "anthropic>=0.40",
    "rapidfuzz>=3.6",
    "python-dateutil>=2.9",
    "typer>=0.12",
]

[project.scripts]
io = "io_assistant.cli:app"

[dependency-groups]
dev = ["pytest>=8", "pytest-mock>=3.14"]

[tool.pytest.ini_options]
markers = [
    "ollama: requires a running Ollama (set IO_OLLAMA_TESTS=1)",
    "anthropic: requires ANTHROPIC_API_KEY (set IO_ANTHROPIC_TESTS=1)",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

- [ ] **Step 2: Create `config.toml`**

```toml
database_url = "postgresql+psycopg://io:io@localhost:5432/io"
embedding_dim = 768

[backend]
provider = "local"          # "local" | "anthropic" | "hybrid"
profile = "light"           # "light" | "quality"
anthropic_model = "claude-haiku-4-5"
ollama_url = "http://localhost:11434"
ollama_keep_alive = "30s"
instruct_model = "llama3.2:3b"   # overridden per-profile in load_config
embed_model = "nomic-embed-text"
num_thread = 0              # 0 = auto (physical cores - 2)

[resolver]
fuzzy_threshold = 92
vector_similarity_threshold = 0.85
confidence_gate_threshold = 0.6
```

- [ ] **Step 3: Create `.env.example`**

```
# Copy to .env for local overrides. Never commit .env.
IO_DATABASE_URL=postgresql+psycopg://io:io@localhost:5432/io
IO_TEST_DATABASE_URL=postgresql+psycopg://io:io@localhost:5432/io_test
# Only needed when backend.provider is "anthropic" or "hybrid":
# ANTHROPIC_API_KEY=sk-ant-...
```

- [ ] **Step 4: Write the failing test** — `tests/test_config.py`

```python
from pathlib import Path
import textwrap
import pytest
from io_assistant.config import load_config, ConfigError

def write_toml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.toml"
    p.write_text(textwrap.dedent(body))
    return p

def test_loads_defaults(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://u:p@localhost/db"
        embedding_dim = 768
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    cfg = load_config(p)
    assert cfg.backend.provider == "local"
    assert cfg.resolver.fuzzy_threshold == 92
    assert cfg.embedding_dim == 768

def test_light_profile_sets_instruct_model(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://u:p@localhost/db"
        embedding_dim = 768
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "IGNORED"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    cfg = load_config(p)
    assert cfg.backend.instruct_model == "llama3.2:3b"   # light profile default

def test_invalid_provider_raises(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "x"
        embedding_dim = 768
        [backend]
        provider = "banana"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    with pytest.raises(ConfigError):
        load_config(p)

def test_env_overrides_database_url(tmp_path, monkeypatch):
    monkeypatch.setenv("IO_DATABASE_URL", "postgresql+psycopg://env@localhost/envdb")
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://file@localhost/filedb"
        embedding_dim = 768
        [backend]
        provider = "local"
        profile = "light"
        anthropic_model = "claude-haiku-4-5"
        ollama_url = "http://localhost:11434"
        ollama_keep_alive = "30s"
        instruct_model = "llama3.2:3b"
        embed_model = "nomic-embed-text"
        num_thread = 0
        [resolver]
        fuzzy_threshold = 92
        vector_similarity_threshold = 0.85
        confidence_gate_threshold = 0.6
    """)
    cfg = load_config(p)
    assert cfg.database_url == "postgresql+psycopg://env@localhost/envdb"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: io_assistant.config`

- [ ] **Step 6: Implement `io_assistant/__init__.py`** (empty) and `io_assistant/config.py`

```python
from __future__ import annotations
import os
import tomllib
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ValidationError, field_validator

class ConfigError(Exception):
    pass

PROFILE_DEFAULTS = {
    "light":   {"instruct_model": "llama3.2:3b",  "whisper_model": "base"},
    "quality": {"instruct_model": "qwen2.5:7b",   "whisper_model": "small"},
}

class BackendConfig(BaseModel):
    provider: Literal["local", "anthropic", "hybrid"]
    profile: Literal["light", "quality"]
    anthropic_model: str
    ollama_url: str
    ollama_keep_alive: str
    instruct_model: str
    embed_model: str
    num_thread: int

class ResolverConfig(BaseModel):
    fuzzy_threshold: int
    vector_similarity_threshold: float
    confidence_gate_threshold: float

class Config(BaseModel):
    database_url: str
    embedding_dim: int
    backend: BackendConfig
    resolver: ResolverConfig

def _repo_root_config() -> Path:
    return Path(__file__).resolve().parent.parent / "config.toml"

def load_config(path: str | Path | None = None) -> Config:
    p = Path(path) if path is not None else _repo_root_config()
    if not p.exists():
        raise ConfigError(f"config file not found: {p}")
    try:
        raw = tomllib.loads(p.read_text())
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"invalid TOML in {p}: {e}") from e

    # env overrides
    if env_db := os.environ.get("IO_DATABASE_URL"):
        raw["database_url"] = env_db

    # profile defaults override the file's instruct_model
    backend = raw.get("backend", {})
    profile = backend.get("profile")
    if profile in PROFILE_DEFAULTS:
        backend["instruct_model"] = PROFILE_DEFAULTS[profile]["instruct_model"]

    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(str(e)) from e
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (4 tests)

- [ ] **Step 8: Add the config fixture to `tests/conftest.py`**

```python
import pytest
from io_assistant.config import Config, BackendConfig, ResolverConfig

@pytest.fixture
def config() -> Config:
    return Config(
        database_url="postgresql+psycopg://io:io@localhost:5432/io_test",
        embedding_dim=768,
        backend=BackendConfig(
            provider="local", profile="light",
            anthropic_model="claude-haiku-4-5",
            ollama_url="http://localhost:11434", ollama_keep_alive="30s",
            instruct_model="llama3.2:3b", embed_model="nomic-embed-text",
            num_thread=0,
        ),
        resolver=ResolverConfig(
            fuzzy_threshold=92, vector_similarity_threshold=0.85,
            confidence_gate_threshold=0.6,
        ),
    )
```

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml config.toml .env.example io_assistant/ tests/
git commit -m "feat: project scaffold and config loader"
```

---

## Task 2: `.claude/` memory scaffold + CLAUDE.md

**Files:**
- Create: `.claude/knowledge/*.md`, `.claude/rules/*.md`, `.claude/skills/*.md`, `.claude/state/{backlog,completed,session}.md`, `CLAUDE.md`
- Test: none (documentation task — verified by the self-review checklist and a presence check folded into Task 16's e2e run is unnecessary; this task's deliverable is the files themselves).

**Interfaces:**
- Consumes: the spec.
- Produces: the memory scaffold that every later session reads.

- [ ] **Step 1: Create `.claude/rules/local-first.md`**

```markdown
# Rule: local-first

IO runs entirely on the user's machine by default. The ONLY permitted non-local
network traffic is to `api.anthropic.com`, and ONLY when `backend.provider` in
config.toml is "anthropic" or "hybrid". No telemetry, no analytics, no CDN
assets, no bundled cloud calls. Any other outbound connection to a non-local
host is a bug. The test suite enforces this (`tests/test_e2e_store.py` socket
guard).
```

- [ ] **Step 2: Create `.claude/rules/llm-boundaries.md`**

```markdown
# Rule: LLM boundaries

The model (local or cloud) is called ONLY for: route, extract, plan, phrase.
It must never: emit SQL, do date arithmetic, filter data, rank data, decide
entity identity. All of that is deterministic Python (resolve/, persist/,
query/, resolve/dates.py). This boundary is what makes the local/cloud backend
swap safe — a weaker model extracts less well but cannot corrupt the datastore.
```

- [ ] **Step 3: Create `.claude/rules/test-discipline.md`**

```markdown
# Rule: test discipline

TDD: failing test first, watch it fail, minimal implementation, watch it pass,
commit. Never mock the database — tests run against the real PostgreSQL named by
IO_TEST_DATABASE_URL. Backend model calls may be faked via the FakeBackend test
double; the persistence, resolver, and SQL layers never are.
```

- [ ] **Step 4: Create `.claude/rules/migrations.md`**

```markdown
# Rule: migrations

Every schema change is an Alembic migration in io_assistant/db/migrations/versions/.
No ad-hoc ALTER. The embedding dimension is fixed (config.embedding_dim); changing
it or the embedding model requires a migration plus a backfill of every embedding
column.
```

- [ ] **Step 5: Create `.claude/rules/resource-budget.md`**

```markdown
# Rule: resource budget

The default ("light") profile must leave the laptop usable during normal work.
LocalBackend enforces: on-demand model loading (no preload), short Ollama
keep_alive, OLLAMA_MAX_LOADED_MODELS=1, OLLAMA_NUM_PARALLEL=1, num_thread capped
at (physical cores - 2). The "quality" profile is opt-in and may make the machine
sluggish during a call.
```

- [ ] **Step 6: Create the `.claude/knowledge/` files**

Create each of these with content summarized from the matching spec section
(1–3 short paragraphs each, enough that a fresh session doesn't re-derive it):
- `architecture.md` — from spec §2 (layer table, data flow, the LLM boundary).
- `data-model.md` — from spec §3 (tables, link tables, indexing, embeddings).
- `extraction.md` — from spec §4 (schema, resolver order, gate triggers, date grounding).
- `query-pipeline.md` — from spec §5 (planner, hybrid retrieval, ranking) — mark "implemented in Plan 2".
- `local-stack.md` — from spec §8 + §13.2 (Ollama/Whisper/Postgres setup, profile model names, 3060 6GB / 24GB notes).
- `model-backends.md` — from spec §13 (Backend interface, local/anthropic/hybrid, when to switch, embeddings always local).
- `conventions.md` — package name `io_assistant`, CLI `io`, TDD, one `config.toml`, `uv run` for everything, test markers.

- [ ] **Step 7: Create the `.claude/skills/` files**

- `add-entity-type.md` — checklist: add ORM model + link table → Alembic migration → extend `extract/schema.py` + few-shot → add resolver branch → add persist handling → add fixtures to `tests/fixtures/utterances_store.json` → tests.
- `add-query-capability.md` — mark "Plan 2".
- `run-local.md` — exact commands: start Postgres, `createdb io`, enable `pgvector` (`CREATE EXTENSION vector;`), `ollama pull llama3.2:3b`, `ollama pull nomic-embed-text`, `uv run alembic upgrade head`, `uv run io repl`.

- [ ] **Step 8: Create the `.claude/state/` files**

`backlog.md`:
```markdown
# Backlog (highest priority on top)

- Plan 2: query pipeline (planner, SQL compiler, hybrid retrieval, respond)
- Plan 3: FastAPI service + pywebview desktop app
- Plan 4: voice (faster-whisper, push-to-talk, passive mode, io doctor)
```

`completed.md`:
```markdown
# Completed (newest first)

_(nothing yet)_
```

`session.md`:
```markdown
# Current session

**Working on:** Plan 1 — core storage pipeline
**Plan:** docs/superpowers/plans/2026-09-07-io-phase-1-core-storage.md
**Knowledge in play:** architecture.md, data-model.md, extraction.md, model-backends.md
**Skills in play:** run-local.md
```

- [ ] **Step 9: Create `CLAUDE.md`**

```markdown
# IO

Local-first, single-user AI assistant. See docs/superpowers/specs/2026-09-07-io-phase-1-design.md.

## First, every session

Read `.claude/state/session.md` to see what's in progress and which knowledge
files and skills are relevant.

## Prime directive

**Local-first.** IO runs on the user's machine. The only sanctioned non-local
network call is the opt-in Anthropic backend (`backend.provider` = "anthropic" or
"hybrid" in config.toml). Everything else stays local.

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
```

- [ ] **Step 10: Commit**

```bash
git add .claude/ CLAUDE.md
git commit -m "docs: .claude memory scaffold and CLAUDE.md"
```

---

## Task 3: Database ORM models + initial migration

**Files:**
- Create: `io_assistant/db/__init__.py`, `io_assistant/db/base.py`, `io_assistant/db/models.py`, `alembic.ini`, `io_assistant/db/migrations/env.py`, `io_assistant/db/migrations/script.py.mako`, `io_assistant/db/migrations/versions/0001_initial.py`
- Test: `tests/test_db_models.py`, `tests/conftest.py` (add DB fixtures)

**Interfaces:**
- Consumes: `Config` (Task 1).
- Produces:
  - `io_assistant.db.base.make_engine(database_url: str)` → SQLAlchemy `Engine`.
  - `io_assistant.db.base.SessionLocal` — a `sessionmaker`; `make_session_factory(engine)`.
  - `io_assistant.db.base.Base` — the declarative base (`Base.metadata` for tests).
  - ORM classes in `io_assistant.db.models`: `Utterance`, `Person`, `Place`, `Item`,
    `Event`, `Task`, `Occasion`, `EventPerson`, `EventPlace`, `EventItem`,
    `EventOccasion`, `OccasionPerson`.
  - Column contracts (later tasks depend on these names):
    - `Utterance(id: int pk, text: str, source: str, captured_at: datetime,
      transcription_confidence: float | None, resolved_intent: str | None,
      marker: str | None)` — `marker` holds e.g. `"extraction_failed"`.
    - `Person(id, canonical_name: str, aliases: list[str], notes: str | None,
      embedding: Vector(768), created_at, updated_at)`.
    - `Place(id, name, type: str | None, aliases: list[str], embedding, created_at, updated_at)`.
    - `Item(id, name, category: str | None, aliases: list[str], embedding, created_at, updated_at)`.
    - `Event(id, description: str, occurred_at: datetime, attributes: dict,
      source_utterance_id: int fk, embedding, created_at)`.
    - `Task(id, title: str, source: str, assigned_by_person_id: int | None fk,
      due_at: datetime | None, status: str, recurrence_rule: str | None,
      attributes: dict, source_utterance_id: int fk, embedding, created_at, updated_at)`.
    - `Occasion(id, name: str, date: date | None, recurrence_rule: str | None,
      embedding, created_at, updated_at)`.
    - link rows: `EventPerson(event_id, person_id, role: str | None)` etc.

- [ ] **Step 1: Implement `io_assistant/db/base.py`**

```python
from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

class Base(DeclarativeBase):
    pass

def make_engine(database_url: str):
    return create_engine(database_url, future=True)

def make_session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)
```

- [ ] **Step 2: Implement `io_assistant/db/models.py`**

```python
from __future__ import annotations
import datetime as dt
from sqlalchemy import (
    BigInteger, Column, Date, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from .base import Base

EMBED_DIM = 768  # keep in sync with config.embedding_dim; migration owns the DDL

class Utterance(Base):
    __tablename__ = "utterances"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # voice|text
    captured_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    transcription_confidence: Mapped[float | None] = mapped_column(nullable=True)
    resolved_intent: Mapped[str | None] = mapped_column(String(16), nullable=True)
    marker: Mapped[str | None] = mapped_column(String(32), nullable=True)

class Person(Base):
    __tablename__ = "people"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

# Place, Item — same shape as Person with (name, type|category) instead of canonical_name.
# Event, Task, Occasion, and link tables per the Interfaces block above.
# Link tables use a composite PK, e.g.:
class EventPerson(Base):
    __tablename__ = "event_people"
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Write out the full set of classes (Place, Item, Event, Task, Occasion,
EventPlace, EventItem, EventOccasion, OccasionPerson) following the exact column
contracts in the Interfaces block. Do not abbreviate in the real file.

- [ ] **Step 3: Set up Alembic** — `alembic.ini` (script location `io_assistant/db/migrations`), `env.py` wiring `target_metadata = Base.metadata` and importing `io_assistant.db.models`, reading the URL from `IO_DATABASE_URL` env or `load_config().database_url`.

- [ ] **Step 4: Write `0001_initial.py`** — creates `CREATE EXTENSION IF NOT EXISTS vector;` first, then all tables, then indexes: b-tree on every FK and on `utterances.captured_at`, `events.occurred_at`, `tasks.due_at`, `occasions.date`; GIN on `people.aliases`, `places.aliases`, `items.aliases`; HNSW on every `embedding` column, e.g.
  `op.execute("CREATE INDEX ix_people_embedding ON people USING hnsw (embedding vector_cosine_ops)")`.

- [ ] **Step 5: Add DB fixtures to `tests/conftest.py`**

```python
import os
import pytest
from sqlalchemy import text
from io_assistant.db.base import make_engine, make_session_factory, Base
from io_assistant.db import models  # noqa: F401 — register mappers

TEST_DB_URL = os.environ.get("IO_TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not TEST_DB_URL, reason="IO_TEST_DATABASE_URL not set")

@pytest.fixture(scope="session")
def engine():
    if not TEST_DB_URL:
        pytest.skip("IO_TEST_DATABASE_URL not set")
    eng = make_engine(TEST_DB_URL)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)

@pytest.fixture
def db(engine):
    """Function-scoped session wrapped in a rolled-back transaction."""
    connection = engine.connect()
    trans = connection.begin()
    Session = make_session_factory(connection)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()
```

- [ ] **Step 6: Write the failing test** — `tests/test_db_models.py`

```python
import datetime as dt
from tests.conftest import requires_db
from io_assistant.db import models as m

@requires_db
def test_insert_utterance_and_event_with_links(db):
    u = m.Utterance(text="dinner at Arcadian", source="text",
                    captured_at=dt.datetime.now(dt.timezone.utc))
    db.add(u); db.flush()
    p = m.Person(canonical_name="Nafay", aliases=["nafay"])
    place = m.Place(name="Arcadian", type="restaurant", aliases=[])
    db.add_all([p, place]); db.flush()
    e = m.Event(description="dinner", occurred_at=dt.datetime.now(dt.timezone.utc),
                attributes={"occasion": "birthday"}, source_utterance_id=u.id)
    db.add(e); db.flush()
    db.add(m.EventPerson(event_id=e.id, person_id=p.id))
    db.add(m.EventPlace(event_id=e.id, place_id=place.id))
    db.flush()
    got = db.get(m.Event, e.id)
    assert got.attributes["occasion"] == "birthday"
    assert db.query(m.EventPerson).filter_by(event_id=e.id).count() == 1
```

- [ ] **Step 7: Run migration + test**

Run: `uv run alembic upgrade head` (against `IO_TEST_DATABASE_URL`), then
`uv run pytest tests/test_db_models.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add io_assistant/db/ alembic.ini tests/
git commit -m "feat: database ORM models and initial migration"
```

---

## Task 4: Domain types + `FakeBackend` test double

**Files:**
- Create: `io_assistant/models_domain.py`
- Test: `tests/conftest.py` (add `FakeBackend`), `tests/test_backend_interface.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Intent` = `Literal["store", "query", "unknown"]`
  - `AnswerShape` = `Literal["text", "markdown", "diagram"]`
  - `Utterance` (pydantic): `text: str`, `source: Literal["voice","text"]`,
    `captured_at: datetime`, `transcription_confidence: float | None = None`
  - `ExtractedPerson`/`ExtractedPlace`/`ExtractedItem` (pydantic):
    `name: str`, `aliases: list[str] = []`, `confidence: float`
  - `ExtractedOccasion`: `name: str`, `date_phrase: str | None`, `confidence: float`
  - `ExtractedEvent`: `description: str`, `when_phrase: str | None`,
    `people: list[str] = []`, `places: list[str] = []`, `items: list[str] = []`,
    `occasions: list[str] = []`, `attributes: dict = {}`, `confidence: float`
  - `ExtractedTask`: `title: str`, `source: Literal["family","job","chore","self"]`,
    `assigned_by: str | None`, `due_phrase: str | None`,
    `recurrence_phrase: str | None`, `attributes: dict = {}`, `confidence: float`
  - `ExtractionResult`: `people: list[ExtractedPerson] = []`,
    `places: list[ExtractedPlace] = []`, `items: list[ExtractedItem] = []`,
    `occasions: list[ExtractedOccasion] = []`, `events: list[ExtractedEvent] = []`,
    `tasks: list[ExtractedTask] = []`
  - `Backend` (Protocol) in `io_assistant/backend/interface.py`:
    - `route(self, utterance: str) -> Intent`
    - `extract(self, utterance: str, now: datetime) -> ExtractionResult`
    - `plan(self, question: str, now: datetime) -> dict`  *(QueryPlan lands in Plan 2; typed as `dict` here)*
    - `phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str`

- [ ] **Step 1: Write the failing test** — `tests/test_backend_interface.py`

```python
import datetime as dt
from io_assistant.backend.interface import Backend
from io_assistant.models_domain import ExtractionResult

def test_fakebackend_satisfies_protocol(fake_backend):
    assert isinstance(fake_backend, Backend)

def test_fakebackend_extract_returns_result(fake_backend):
    fake_backend.set_extraction(ExtractionResult(events=[]))
    out = fake_backend.extract("hi", dt.datetime.now(dt.timezone.utc))
    assert isinstance(out, ExtractionResult)

def test_fakebackend_route_returns_configured_intent(fake_backend):
    fake_backend.set_intent("store")
    assert fake_backend.route("anything") == "store"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_backend_interface.py -v`
Expected: FAIL — `ModuleNotFoundError` / no `fake_backend` fixture

- [ ] **Step 3: Implement `io_assistant/models_domain.py`** per the Interfaces block (all pydantic `BaseModel`s and the two `Literal` aliases).

- [ ] **Step 4: Implement `io_assistant/backend/interface.py`**

```python
from __future__ import annotations
from datetime import datetime
from typing import Protocol, runtime_checkable
from io_assistant.models_domain import ExtractionResult, Intent, AnswerShape

@runtime_checkable
class Backend(Protocol):
    def route(self, utterance: str) -> Intent: ...
    def extract(self, utterance: str, now: datetime) -> ExtractionResult: ...
    def plan(self, question: str, now: datetime) -> dict: ...
    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str: ...
```

- [ ] **Step 5: Add `FakeBackend` + fixture to `tests/conftest.py`**

```python
from datetime import datetime
from io_assistant.models_domain import ExtractionResult, Intent, AnswerShape

class FakeBackend:
    def __init__(self):
        self._intent: Intent = "unknown"
        self._extraction = ExtractionResult()
        self._answer = ""
        self.calls: list[str] = []
    def set_intent(self, i: Intent): self._intent = i
    def set_extraction(self, r: ExtractionResult): self._extraction = r
    def set_answer(self, s: str): self._answer = s
    def route(self, utterance: str) -> Intent:
        self.calls.append("route"); return self._intent
    def extract(self, utterance: str, now: datetime) -> ExtractionResult:
        self.calls.append("extract"); return self._extraction
    def plan(self, question: str, now: datetime) -> dict:
        self.calls.append("plan"); return {}
    def phrase(self, question, rows, shape: AnswerShape) -> str:
        self.calls.append("phrase"); return self._answer

@pytest.fixture
def fake_backend():
    return FakeBackend()
```

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/test_backend_interface.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add io_assistant/models_domain.py io_assistant/backend/ tests/
git commit -m "feat: domain types and Backend protocol with FakeBackend"
```

---

## Task 5: `embed()` — local embedding via Ollama

**Files:**
- Create: `io_assistant/backend/embed.py`
- Test: `tests/test_embed.py`

**Interfaces:**
- Consumes: `Config` (`backend.ollama_url`, `backend.embed_model`, `embedding_dim`).
- Produces:
  - `io_assistant.backend.embed.Embedder(config: Config)` with
    `embed(self, texts: list[str]) -> list[list[float]]` — POSTs to
    `{ollama_url}/api/embed` with `{"model": embed_model, "input": texts}`,
    returns one vector per input. Raises `EmbedError` on HTTP failure or on a
    dimension mismatch with `config.embedding_dim`.
  - `embed_one(self, text: str) -> list[float]`.

- [ ] **Step 1: Write the failing test** — `tests/test_embed.py`

```python
import pytest
import httpx
from io_assistant.backend.embed import Embedder, EmbedError

def test_embed_posts_and_returns_vectors(config, respx_mock=None, monkeypatch):
    calls = {}
    class FakeResp:
        status_code = 200
        def json(self): return {"embeddings": [[0.1]*768, [0.2]*768]}
        def raise_for_status(self): pass
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json):
            calls["url"] = url; calls["json"] = json
            return FakeResp()
    monkeypatch.setattr(httpx, "Client", FakeClient)
    out = Embedder(config).embed(["a", "b"])
    assert calls["url"].endswith("/api/embed")
    assert calls["json"]["model"] == "nomic-embed-text"
    assert len(out) == 2 and len(out[0]) == 768

def test_embed_dimension_mismatch_raises(config, monkeypatch):
    class FakeResp:
        status_code = 200
        def json(self): return {"embeddings": [[0.1]*10]}
        def raise_for_status(self): pass
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): return FakeResp()
    monkeypatch.setattr(httpx, "Client", FakeClient)
    with pytest.raises(EmbedError):
        Embedder(config).embed(["a"])
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_embed.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `io_assistant/backend/embed.py`**

```python
from __future__ import annotations
import httpx
from io_assistant.config import Config

class EmbedError(Exception):
    pass

class Embedder:
    def __init__(self, config: Config):
        self._url = config.backend.ollama_url.rstrip("/") + "/api/embed"
        self._model = config.backend.embed_model
        self._dim = config.embedding_dim
        self._keep_alive = config.backend.ollama_keep_alive

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(self._url, json={
                    "model": self._model, "input": texts,
                    "keep_alive": self._keep_alive,
                })
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise EmbedError(f"ollama embed failed: {e}") from e
        vecs = data.get("embeddings") or []
        if len(vecs) != len(texts):
            raise EmbedError(f"expected {len(texts)} vectors, got {len(vecs)}")
        for v in vecs:
            if len(v) != self._dim:
                raise EmbedError(f"embedding dim {len(v)} != configured {self._dim}")
        return vecs

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_embed.py -v`
Expected: PASS

- [ ] **Step 5: Add an `@pytest.mark.ollama` real round-trip test**

```python
import os
import pytest

@pytest.mark.ollama
@pytest.mark.skipif(os.environ.get("IO_OLLAMA_TESTS") != "1", reason="opt-in")
def test_embed_real_ollama(config):
    from io_assistant.backend.embed import Embedder
    v = Embedder(config).embed_one("hello world")
    assert len(v) == config.embedding_dim
```

- [ ] **Step 6: Commit**

```bash
git add io_assistant/backend/embed.py tests/test_embed.py
git commit -m "feat: local embedding via Ollama"
```

---

## Task 6: `LocalBackend` — Ollama chat for route/extract/plan/phrase

**Files:**
- Create: `io_assistant/backend/local.py`, `io_assistant/prompts/route.txt`, `io_assistant/prompts/extract.txt`
- Test: `tests/test_backend_local.py`

**Interfaces:**
- Consumes: `Config`, the prompt files, `ExtractionResult` (Task 4).
- Produces:
  - `io_assistant.backend.local.LocalBackend(config: Config)` implementing `Backend`.
  - Internal: `_chat(system: str, user: str, *, json_mode: bool) -> str` — POSTs to
    `{ollama_url}/api/chat` with `options.num_thread` (resolved from
    `config.backend.num_thread`, `0` → `max(1, physical_cores - 2)` via
    `os.cpu_count()`), `keep_alive`, `format: "json"` when `json_mode`.
  - `route()` returns one of the three intents (defaults to `"unknown"` on any
    unrecognized output).
  - `extract()` parses the JSON response into `ExtractionResult`; raises
    `BackendParseError` if it can't (the Extractor task handles retry, not this).
  - `LocalBackendError` for transport failures.

- [ ] **Step 1: Write the failing test** — `tests/test_backend_local.py`

```python
import datetime as dt
import httpx
import pytest
from io_assistant.backend.local import LocalBackend, BackendParseError

def _patch_chat(monkeypatch, content: str):
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"message": {"content": content}}
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json): FakeClient.last = json; return FakeResp()
    monkeypatch.setattr(httpx, "Client", FakeClient)
    return FakeClient

def test_route_parses_intent(config, monkeypatch):
    _patch_chat(monkeypatch, "STORE")
    assert LocalBackend(config).route("I ate at Arcadian") == "store"

def test_route_unknown_on_garbage(config, monkeypatch):
    _patch_chat(monkeypatch, "banana pudding")
    assert LocalBackend(config).route("???") == "unknown"

def test_extract_parses_result(config, monkeypatch):
    _patch_chat(monkeypatch, '{"people":[{"name":"Nafay","aliases":[],"confidence":0.9}],'
                             '"places":[],"items":[],"occasions":[],"events":[],"tasks":[]}')
    r = LocalBackend(config).extract("saw Nafay", dt.datetime.now(dt.timezone.utc))
    assert r.people[0].name == "Nafay"

def test_extract_bad_json_raises(config, monkeypatch):
    _patch_chat(monkeypatch, "not json at all")
    with pytest.raises(BackendParseError):
        LocalBackend(config).extract("x", dt.datetime.now(dt.timezone.utc))

def test_chat_sets_num_thread_and_keep_alive(config, monkeypatch):
    fc = _patch_chat(monkeypatch, "QUERY")
    LocalBackend(config).route("what did I do today")
    assert "num_thread" in fc.last["options"]
    assert fc.last["keep_alive"] == "30s"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_backend_local.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Create `io_assistant/prompts/route.txt`**

```
You classify a single user utterance into exactly one intent.
Reply with ONE word, uppercase, nothing else:
STORE  - the user is telling you something to remember (an event, task, fact)
QUERY  - the user is asking a question about things they told you before
UNKNOWN - anything else

Utterance:
{utterance}
```

- [ ] **Step 4: Create `io_assistant/prompts/extract.txt`**

```
You extract structured data from one utterance. Output JSON ONLY, matching this shape:
{schema}

Rules:
- Only include fields you can fill from the utterance.
- Every record needs a "confidence" between 0 and 1.
- Do NOT resolve dates. Put the raw phrase in "when_phrase" / "due_phrase" / "date_phrase".
- People/places/items are referenced by name strings inside events/tasks AND listed
  in the top-level arrays.

Examples:
{examples}

Utterance (assume "now" is {now}):
{utterance}
```

- [ ] **Step 5: Implement `io_assistant/backend/local.py`**

```python
from __future__ import annotations
import json
import os
from datetime import datetime
from importlib import resources
import httpx
from io_assistant.config import Config
from io_assistant.models_domain import ExtractionResult, Intent, AnswerShape
from io_assistant.extract.schema import SCHEMA_JSON, FEWSHOT   # Task 8 provides these

class LocalBackendError(Exception): pass
class BackendParseError(Exception): pass

_INTENTS = {"STORE": "store", "QUERY": "query", "UNKNOWN": "unknown"}

def _load_prompt(name: str) -> str:
    return resources.files("io_assistant.prompts").joinpath(name).read_text()

def _resolve_threads(n: int) -> int:
    if n and n > 0:
        return n
    return max(1, (os.cpu_count() or 4) - 2)

class LocalBackend:
    def __init__(self, config: Config):
        self._url = config.backend.ollama_url.rstrip("/") + "/api/chat"
        self._model = config.backend.instruct_model
        self._keep_alive = config.backend.ollama_keep_alive
        self._num_thread = _resolve_threads(config.backend.num_thread)

    def _chat(self, system: str, user: str, *, json_mode: bool) -> str:
        body = {
            "model": self._model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "stream": False,
            "keep_alive": self._keep_alive,
            "options": {"num_thread": self._num_thread, "temperature": 0},
        }
        if json_mode:
            body["format"] = "json"
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(self._url, json=body)
                resp.raise_for_status()
                return resp.json()["message"]["content"]
        except httpx.HTTPError as e:
            raise LocalBackendError(f"ollama chat failed: {e}") from e

    def route(self, utterance: str) -> Intent:
        out = self._chat("You are a precise classifier.",
                         _load_prompt("route.txt").format(utterance=utterance),
                         json_mode=False)
        token = out.strip().upper().split()[0] if out.strip() else ""
        return _INTENTS.get(token, "unknown")

    def extract(self, utterance: str, now: datetime) -> ExtractionResult:
        prompt = _load_prompt("extract.txt").format(
            schema=SCHEMA_JSON, examples=FEWSHOT, now=now.isoformat(), utterance=utterance)
        out = self._chat("You extract structured data. Output JSON only.", prompt, json_mode=True)
        try:
            return ExtractionResult.model_validate_json(out)
        except Exception as e:
            raise BackendParseError(str(e)) from e

    def plan(self, question: str, now: datetime) -> dict:
        raise NotImplementedError("QueryPlan lands in Plan 2")

    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str:
        raise NotImplementedError("phrasing lands in Plan 2")
```

Note the import from `io_assistant.extract.schema` — Task 8 creates it. If executing
strictly in order, create a minimal `io_assistant/extract/__init__.py` +
`schema.py` stub with `SCHEMA_JSON = "{}"` and `FEWSHOT = ""` now and flesh it out
in Task 8. Add a `- [ ]` sub-step for that stub.

- [ ] **Step 6: Run to verify it passes**

Run: `uv run pytest tests/test_backend_local.py -v`
Expected: PASS (5 tests)

- [ ] **Step 7: Commit**

```bash
git add io_assistant/backend/local.py io_assistant/prompts/ io_assistant/extract/
git commit -m "feat: LocalBackend (Ollama) for route and extract"
```

---

## Task 7: `AnthropicBackend`

**Files:**
- Create: `io_assistant/backend/anthropic_backend.py`
- Test: `tests/test_backend_anthropic.py`

**Interfaces:**
- Consumes: `Config` (`backend.anthropic_model`), `ANTHROPIC_API_KEY` from env
  (read by the `anthropic` SDK itself — never from `config.toml`).
- Produces:
  - `io_assistant.backend.anthropic_backend.AnthropicBackend(config: Config, client=None)`
    implementing `Backend`. `client` is injectable for tests; default constructs
    `anthropic.Anthropic()`.
  - Same `route()` / `extract()` semantics and the same `BackendParseError` /
    `AnthropicBackendError` contract as `LocalBackend`.
  - Uses `client.messages.create(model=..., max_tokens=2048, system=..., messages=[...])`.
    For `extract`, instructs JSON output via the system prompt and parses the first
    text block (no prefill — prefill is rejected on current models).

- [ ] **Step 1: Write the failing test** — `tests/test_backend_anthropic.py`

```python
import datetime as dt
import pytest
from io_assistant.backend.anthropic_backend import AnthropicBackend, BackendParseError

class FakeBlock:
    def __init__(self, text): self.text = text; self.type = "text"
class FakeMsg:
    def __init__(self, text): self.content = [FakeBlock(text)]
class FakeMessages:
    def __init__(self, text): self._text = text; self.last_kwargs = None
    def create(self, **kwargs): self.last_kwargs = kwargs; return FakeMsg(self._text)
class FakeClient:
    def __init__(self, text): self.messages = FakeMessages(text)

def test_route_maps_intent(config):
    c = FakeClient("QUERY")
    assert AnthropicBackend(config, client=c).route("what did I eat") == "query"
    assert c.messages.last_kwargs["model"] == "claude-haiku-4-5"

def test_extract_parses(config):
    payload = ('{"people":[],"places":[{"name":"Arcadian","aliases":[],"confidence":0.8}],'
               '"items":[],"occasions":[],"events":[],"tasks":[]}')
    c = FakeClient(payload)
    r = AnthropicBackend(config, client=c).extract("ate at Arcadian", dt.datetime.now(dt.timezone.utc))
    assert r.places[0].name == "Arcadian"

def test_extract_bad_json_raises(config):
    with pytest.raises(BackendParseError):
        AnthropicBackend(config, client=FakeClient("sorry, no")).extract(
            "x", dt.datetime.now(dt.timezone.utc))
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_backend_anthropic.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Implement `io_assistant/backend/anthropic_backend.py`**

```python
from __future__ import annotations
from datetime import datetime
from importlib import resources
from io_assistant.config import Config
from io_assistant.models_domain import ExtractionResult, Intent, AnswerShape
from io_assistant.extract.schema import SCHEMA_JSON, FEWSHOT

class AnthropicBackendError(Exception): pass
class BackendParseError(Exception): pass

_INTENTS = {"STORE": "store", "QUERY": "query", "UNKNOWN": "unknown"}

def _prompt(name: str) -> str:
    return resources.files("io_assistant.prompts").joinpath(name).read_text()

class AnthropicBackend:
    def __init__(self, config: Config, client=None):
        self._model = config.backend.anthropic_model
        if client is None:
            import anthropic
            client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY / ant profile
        self._client = client

    def _complete(self, system: str, user: str) -> str:
        try:
            msg = self._client.messages.create(
                model=self._model, max_tokens=2048,
                system=system, messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            raise AnthropicBackendError(str(e)) from e
        parts = [b.text for b in msg.content if getattr(b, "type", None) == "text"]
        return "".join(parts).strip()

    def route(self, utterance: str) -> Intent:
        out = self._complete("You are a precise classifier. Reply with one word.",
                             _prompt("route.txt").format(utterance=utterance))
        token = out.upper().split()[0] if out else ""
        return _INTENTS.get(token, "unknown")

    def extract(self, utterance: str, now: datetime) -> ExtractionResult:
        user = _prompt("extract.txt").format(
            schema=SCHEMA_JSON, examples=FEWSHOT, now=now.isoformat(), utterance=utterance)
        out = self._complete(
            "You extract structured data. Output a single JSON object and nothing else.", user)
        # tolerate ```json fences
        out = out.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return ExtractionResult.model_validate_json(out)
        except Exception as e:
            raise BackendParseError(str(e)) from e

    def plan(self, question: str, now: datetime) -> dict:
        raise NotImplementedError("Plan 2")

    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str:
        raise NotImplementedError("Plan 2")
```

- [ ] **Step 4: Run to verify it passes** — `uv run pytest tests/test_backend_anthropic.py -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add io_assistant/backend/anthropic_backend.py tests/test_backend_anthropic.py
git commit -m "feat: AnthropicBackend"
```

---

## Task 8: Extraction schema + few-shot examples

**Files:**
- Create/replace: `io_assistant/extract/__init__.py`, `io_assistant/extract/schema.py`
- Test: `tests/test_extract_schema.py`, `tests/fixtures/utterances_store.json`

**Interfaces:**
- Consumes: the pydantic models from `models_domain` (Task 4).
- Produces:
  - `io_assistant.extract.schema.SCHEMA_JSON: str` — `ExtractionResult.model_json_schema()`
    dumped to a compact JSON string.
  - `io_assistant.extract.schema.FEWSHOT: str` — 2–3 worked examples
    (utterance → JSON), including the Arcadian sentence.
  - `tests/fixtures/utterances_store.json` — a list of
    `{"utterance": str, "expect": {...}}` where `expect` names the entities/events
    that must appear (used by Task 9 and the e2e task). At least 5 entries.

- [ ] **Step 1: Write the failing test** — `tests/test_extract_schema.py`

```python
import json
from io_assistant.extract.schema import SCHEMA_JSON, FEWSHOT
from io_assistant.models_domain import ExtractionResult

def test_schema_is_valid_json_and_mentions_events():
    obj = json.loads(SCHEMA_JSON)
    assert "properties" in obj
    assert "events" in json.dumps(obj)

def test_fewshot_examples_parse_as_extraction_results():
    # every ```json block in FEWSHOT must validate
    blocks = [b.split("```")[0] for b in FEWSHOT.split("```json")[1:]]
    assert blocks, "no examples found"
    for b in blocks:
        ExtractionResult.model_validate_json(b)

def test_fixtures_file_wellformed():
    import pathlib
    data = json.loads(pathlib.Path("tests/fixtures/utterances_store.json").read_text())
    assert len(data) >= 5
    assert all("utterance" in d and "expect" in d for d in data)
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/test_extract_schema.py -v`

- [ ] **Step 3: Implement `io_assistant/extract/schema.py`**

```python
from __future__ import annotations
import json
from io_assistant.models_domain import ExtractionResult

SCHEMA_JSON = json.dumps(ExtractionResult.model_json_schema(), separators=(",", ":"))

FEWSHOT = '''
Utterance: "I went out with Nafay to eat at Arcadian for his and Eelian's birthday"
```json
{"people":[{"name":"Nafay","aliases":[],"confidence":0.95},
           {"name":"Eelian","aliases":[],"confidence":0.9}],
 "places":[{"name":"Arcadian","aliases":[],"confidence":0.9}],
 "items":[],
 "occasions":[{"name":"Nafay and Eelian's birthday","date_phrase":null,"confidence":0.8}],
 "events":[{"description":"went out to eat","when_phrase":"today","people":["Nafay","Eelian"],
            "places":["Arcadian"],"items":[],"occasions":["Nafay and Eelian's birthday"],
            "attributes":{"meal":"dinner"},"confidence":0.9}],
 "tasks":[]}
```

Utterance: "Mum asked me to pick up groceries tomorrow"
```json
{"people":[{"name":"Mum","aliases":["mom","mother"],"confidence":0.9}],
 "places":[],"items":[{"name":"groceries","aliases":[],"confidence":0.8}],
 "occasions":[],"events":[],
 "tasks":[{"title":"pick up groceries","source":"family","assigned_by":"Mum",
           "due_phrase":"tomorrow","recurrence_phrase":null,"attributes":{},"confidence":0.85}]}
```

Utterance: "I take the trash out every Monday"
```json
{"people":[],"places":[],"items":[{"name":"trash","aliases":[],"confidence":0.7}],
 "occasions":[],"events":[],
 "tasks":[{"title":"take the trash out","source":"chore","assigned_by":null,
           "due_phrase":null,"recurrence_phrase":"every Monday","attributes":{},"confidence":0.9}]}
```
'''
```

- [ ] **Step 4: Create `tests/fixtures/utterances_store.json`** — ≥5 entries, e.g.:

```json
[
  {"utterance": "I went out with Nafay to eat at Arcadian for his and Eelian's birthday",
   "expect": {"people": ["Nafay", "Eelian"], "places": ["Arcadian"], "events": 1}},
  {"utterance": "Mum asked me to pick up groceries tomorrow",
   "expect": {"people": ["Mum"], "tasks": 1, "task_source": "family"}},
  {"utterance": "I take the trash out every Monday",
   "expect": {"tasks": 1, "task_source": "chore", "recurring": true}},
  {"utterance": "Had coffee with Sara at Blue Bottle this morning",
   "expect": {"people": ["Sara"], "places": ["Blue Bottle"], "events": 1}},
  {"utterance": "My manager wants the report done by Friday",
   "expect": {"tasks": 1, "task_source": "job"}}
]
```

- [ ] **Step 5: Run to verify it passes** — `uv run pytest tests/test_extract_schema.py -v` → PASS

- [ ] **Step 6: Commit**

```bash
git add io_assistant/extract/ tests/test_extract_schema.py tests/fixtures/
git commit -m "feat: extraction schema and few-shot examples"
```

---

## Task 9: `Extractor` — validate + one retry

**Files:**
- Create: `io_assistant/extract/extractor.py`
- Test: `tests/test_extractor.py`

**Interfaces:**
- Consumes: `Backend` (Task 4), `ExtractionResult`.
- Produces:
  - `io_assistant.extract.extractor.Extractor(backend: Backend)` with
    `run(self, utterance: str, now: datetime) -> ExtractionResult | None` —
    calls `backend.extract`; on `BackendParseError` retries once with the same
    inputs; returns `None` after a second failure (caller marks the utterance
    `extraction_failed`).
  - Import the two `BackendParseError` classes and catch both (they're distinct
    classes in `local` and `anthropic_backend` — Task 10's factory will not
    unify them, so `extractor.py` defines
    `_PARSE_ERRORS = (LocalParseError, AnthropicParseError)` and catches that
    tuple). *Refactor note:* if the executor prefers, hoist a single
    `BackendParseError` into `io_assistant/backend/interface.py` and have both
    backends raise that — update Tasks 6 and 7 imports. Either is acceptable;
    pick one and be consistent.

- [ ] **Step 1: Write the failing test** — `tests/test_extractor.py`

```python
import datetime as dt
from io_assistant.extract.extractor import Extractor
from io_assistant.models_domain import ExtractionResult

class FlakyBackend:
    def __init__(self, results):  # results: list of ExtractionResult or Exception
        self._results = list(results); self.calls = 0
    def route(self, u): return "store"
    def extract(self, u, now):
        r = self._results[self.calls]; self.calls += 1
        if isinstance(r, Exception): raise r
        return r
    def plan(self, *a): ...
    def phrase(self, *a): ...

def test_returns_result_first_try():
    b = FlakyBackend([ExtractionResult(events=[])])
    out = Extractor(b).run("hi", dt.datetime.now(dt.timezone.utc))
    assert isinstance(out, ExtractionResult) and b.calls == 1

def test_retries_once_then_succeeds():
    from io_assistant.backend.local import BackendParseError
    b = FlakyBackend([BackendParseError("bad"), ExtractionResult(events=[])])
    out = Extractor(b).run("hi", dt.datetime.now(dt.timezone.utc))
    assert isinstance(out, ExtractionResult) and b.calls == 2

def test_returns_none_after_two_failures():
    from io_assistant.backend.local import BackendParseError
    b = FlakyBackend([BackendParseError("x"), BackendParseError("y")])
    out = Extractor(b).run("hi", dt.datetime.now(dt.timezone.utc))
    assert out is None and b.calls == 2
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement `io_assistant/extract/extractor.py`**

```python
from __future__ import annotations
from datetime import datetime
from io_assistant.backend.interface import Backend
from io_assistant.models_domain import ExtractionResult
from io_assistant.backend.local import BackendParseError as LocalParseError
from io_assistant.backend.anthropic_backend import BackendParseError as AnthropicParseError

_PARSE_ERRORS = (LocalParseError, AnthropicParseError)

class Extractor:
    def __init__(self, backend: Backend):
        self._backend = backend

    def run(self, utterance: str, now: datetime) -> ExtractionResult | None:
        for attempt in (1, 2):
            try:
                return self._backend.extract(utterance, now)
            except _PARSE_ERRORS:
                if attempt == 2:
                    return None
        return None
```

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Add `@pytest.mark.ollama` fixture-driven real test**

```python
import json, os, pathlib, datetime as dt
import pytest

@pytest.mark.ollama
@pytest.mark.skipif(os.environ.get("IO_OLLAMA_TESTS") != "1", reason="opt-in")
def test_extractor_against_fixtures(config):
    from io_assistant.backend.local import LocalBackend
    from io_assistant.extract.extractor import Extractor
    ex = Extractor(LocalBackend(config))
    data = json.loads(pathlib.Path("tests/fixtures/utterances_store.json").read_text())
    now = dt.datetime.now(dt.timezone.utc)
    for case in data:
        r = ex.run(case["utterance"], now)
        assert r is not None, case["utterance"]
        names = {p.name.lower() for p in r.people}
        for want in case["expect"].get("people", []):
            assert any(want.lower() in n or n in want.lower() for n in names), (case, names)
```

- [ ] **Step 6: Commit**

```bash
git add io_assistant/extract/extractor.py tests/test_extractor.py
git commit -m "feat: Extractor with single retry"
```

---

## Task 10: `Router`

**Files:**
- Create: `io_assistant/route/__init__.py`, `io_assistant/route/router.py`
- Test: `tests/test_router.py`, `tests/fixtures/utterances_route.json`

**Interfaces:**
- Consumes: `Backend`.
- Produces:
  - `io_assistant.route.router.Router(backend: Backend)` with
    `classify(self, utterance: str) -> Intent`. Thin wrapper over `backend.route`
    that also treats an empty/whitespace utterance as `"unknown"` without calling
    the model.

- [ ] **Step 1: Write the failing test** — `tests/test_router.py`

```python
from io_assistant.route.router import Router

class B:
    def __init__(self, intent): self.intent = intent; self.called = False
    def route(self, u): self.called = True; return self.intent
    def extract(self, *a): ...
    def plan(self, *a): ...
    def phrase(self, *a): ...

def test_delegates_to_backend():
    b = B("store")
    assert Router(b).classify("I ate lunch with Ali") == "store"
    assert b.called

def test_empty_utterance_is_unknown_without_model_call():
    b = B("store")
    assert Router(b).classify("   ") == "unknown"
    assert not b.called
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement `io_assistant/route/router.py`**

```python
from __future__ import annotations
from io_assistant.backend.interface import Backend
from io_assistant.models_domain import Intent

class Router:
    def __init__(self, backend: Backend):
        self._backend = backend

    def classify(self, utterance: str) -> Intent:
        if not utterance or not utterance.strip():
            return "unknown"
        return self._backend.route(utterance)
```

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Create `tests/fixtures/utterances_route.json`** — ≥8 entries mixing store/query/unknown; add an `@pytest.mark.ollama` test that runs `Router(LocalBackend(config))` over them and asserts ≥80% match (models aren't perfect; the fixture doubles as a regression signal).

- [ ] **Step 6: Commit**

```bash
git add io_assistant/route/ tests/test_router.py tests/fixtures/utterances_route.json
git commit -m "feat: Router"
```

---

## Task 11: `ground_dates()` — relative time expressions

**Files:**
- Create: `io_assistant/resolve/__init__.py`, `io_assistant/resolve/dates.py`
- Test: `tests/test_dates.py`

**Interfaces:**
- Consumes: nothing (pure).
- Produces:
  - `io_assistant.resolve.dates.ground(phrase: str | None, now: datetime) -> DateResult`
    where `DateResult` (dataclass) is `{value: datetime | None, ok: bool}`.
    - `None`/empty phrase → `DateResult(None, True)` (absence is fine).
    - "today"/"this morning"/"tonight" → that day (morning=09:00, tonight=20:00, bare today=now).
    - "yesterday" → now − 1 day; "tomorrow" → now + 1 day.
    - "last <weekday>" / "this <weekday>" / "<weekday>" → nearest past / this week / next.
    - "N days ago", "in N days", "last week", "next week".
    - Anything unparseable → `DateResult(None, False)` (triggers the confirmation gate).
  - `io_assistant.resolve.dates.to_rrule(phrase: str | None) -> str | None` —
    "every Monday" → `"FREQ=WEEKLY;BYDAY=MO"`, "daily"/"every day" → `"FREQ=DAILY"`,
    "every weekday" → `"FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"`, "monthly" → `"FREQ=MONTHLY"`.
    Unrecognized → `None`.

- [ ] **Step 1: Write the failing test** — `tests/test_dates.py`

```python
import datetime as dt
from io_assistant.resolve.dates import ground, to_rrule

NOW = dt.datetime(2026, 9, 7, 15, 0, tzinfo=dt.timezone.utc)  # a Monday

def test_none_phrase_ok():
    r = ground(None, NOW)
    assert r.ok and r.value is None

def test_yesterday():
    r = ground("yesterday", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 6)

def test_last_friday():
    r = ground("last Friday", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 4)

def test_unparseable_not_ok():
    r = ground("sometime around the harvest festival", NOW)
    assert not r.ok and r.value is None

def test_rrule_every_monday():
    assert to_rrule("every Monday") == "FREQ=WEEKLY;BYDAY=MO"

def test_rrule_unknown_none():
    assert to_rrule("once in a blue moon") is None
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement `io_assistant/resolve/dates.py`** using `dateutil` and
  explicit rules. Keep it deterministic and small; do not call any model.

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Commit**

```bash
git add io_assistant/resolve/__init__.py io_assistant/resolve/dates.py tests/test_dates.py
git commit -m "feat: deterministic date grounding and RRULE mapping"
```

---

## Task 12: `EntityResolver`

**Files:**
- Create: `io_assistant/resolve/resolver.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: a DB `Session`, `Embedder` (Task 5), `ResolverConfig`, the ORM models.
- Produces:
  - `io_assistant.resolve.resolver.EntityResolver(session, embedder, cfg: ResolverConfig)`
  - `resolve(self, kind: Literal["person","place","item"], name: str, aliases: list[str]) -> ResolveOutcome`
    where `ResolveOutcome` (dataclass): `entity_id: int | None`, `is_new: bool`,
    `ambiguous: bool`, `candidate_id: int | None`, `candidate_name: str | None`.
    - exact (case-insensitive) match on canonical name/name or any alias → `entity_id` set, not ambiguous, not new.
    - else fuzzy (`rapidfuzz.fuzz.token_set_ratio`) ≥ `cfg.fuzzy_threshold` → same.
    - else embed `name`, cosine-search that table; best similarity ≥ `cfg.vector_similarity_threshold` → `ambiguous=True`, `candidate_id`/`candidate_name` set, `entity_id=None`.
    - else → `is_new=True`, `entity_id=None`.
  - `create(self, kind, name, aliases) -> int` — inserts the new entity **without**
    embedding (Persist computes embeddings in its transaction) and returns the id.
    Actually: to keep vector search consistent, `create` should compute and store
    the embedding here. Decision: **Resolver owns entity creation + its embedding**;
    Persist owns event/task rows + their embeddings. Document this split in
    `.claude/knowledge/extraction.md`.

- [ ] **Step 1: Write the failing test** — `tests/test_resolve.py`

```python
import datetime as dt
from tests.conftest import requires_db
from io_assistant.resolve.resolver import EntityResolver
from io_assistant.db import models as m

class StubEmbedder:
    def __init__(self, mapping=None): self.mapping = mapping or {}
    def embed_one(self, text): return self.mapping.get(text, [0.0]*768)
    def embed(self, texts): return [self.embed_one(t) for t in texts]

@requires_db
def test_exact_match(db, config):
    db.add(m.Person(canonical_name="Nafay", aliases=["naf"])); db.flush()
    r = EntityResolver(db, StubEmbedder(), config.resolver)
    out = r.resolve("person", "nafay", [])
    assert out.entity_id is not None and not out.is_new and not out.ambiguous

@requires_db
def test_alias_match(db, config):
    db.add(m.Person(canonical_name="Mother", aliases=["mum", "mom"])); db.flush()
    out = EntityResolver(db, StubEmbedder(), config.resolver).resolve("person", "Mum", [])
    assert out.entity_id is not None

@requires_db
def test_fuzzy_match(db, config):
    db.add(m.Place(name="Blue Bottle Coffee", type=None, aliases=[])); db.flush()
    out = EntityResolver(db, StubEmbedder(), config.resolver).resolve("place", "Blue Bottle", [])
    assert out.entity_id is not None

@requires_db
def test_vector_ambiguous(db, config):
    p = m.Person(canonical_name="Jonathan", aliases=[], embedding=[1.0]+[0.0]*767)
    db.add(p); db.flush()
    emb = StubEmbedder({"Jon": [1.0]+[0.0]*767})
    out = EntityResolver(db, emb, config.resolver).resolve("person", "Jon", [])
    assert out.ambiguous and out.candidate_name == "Jonathan" and out.entity_id is None

@requires_db
def test_new_entity(db, config):
    out = EntityResolver(db, StubEmbedder(), config.resolver).resolve("person", "Zephyr", [])
    assert out.is_new and out.entity_id is None
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement `io_assistant/resolve/resolver.py`** — use SQLAlchemy
  `select`, `func.lower`, `rapidfuzz`, and pgvector's `.cosine_distance()`
  (similarity = `1 - distance`). Table/column per `kind`.

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Commit**

```bash
git add io_assistant/resolve/resolver.py tests/test_resolve.py
git commit -m "feat: EntityResolver (exact/fuzzy/vector/new)"
```

---

## Task 13: `persist_store()` — the write transaction

**Files:**
- Create: `io_assistant/persist/__init__.py`, `io_assistant/persist/writer.py`
- Test: `tests/test_persist.py`

**Interfaces:**
- Consumes: `Session`, `Embedder`, `EntityResolver`, `ExtractionResult`,
  `ground`/`to_rrule` (Task 11), ORM models.
- Produces:
  - `io_assistant.persist.writer.PersistResult` (dataclass):
    `utterance_id: int`, `event_ids: list[int]`, `task_ids: list[int]`,
    `new_entities: list[tuple[str,str]]`, `gated: bool`, `gate_reasons: list[str]`.
  - `io_assistant.persist.writer.persist_store(session, embedder, resolver, *,
      utterance_text: str, source: str, captured_at: datetime,
      extraction: ExtractionResult, now: datetime, confidence_gate: float,
      confirmed: bool = False) -> PersistResult`
    - Always inserts the `Utterance` row first (verbatim), sets `resolved_intent="store"`.
    - Resolves every person/place/item. If any resolve is `ambiguous`, or any
      record `confidence < confidence_gate`, or any date phrase grounds with
      `ok=False`: when `confirmed` is False → set `gated=True`, populate
      `gate_reasons`, **roll back** everything except the utterance row, return.
      When `confirmed` is True → proceed, creating new entities for ambiguous
      resolves.
    - Creates new entities via `resolver.create(...)`.
    - Inserts `Event` rows (`occurred_at` from `ground(when_phrase)`, falling back
      to `now`), computes their embedding from `description`, links people/places/
      items/occasions.
    - Inserts `Task` rows (`due_at` from `ground(due_phrase)`,
      `recurrence_rule` from `to_rrule(recurrence_phrase)`, `status="open"`,
      `assigned_by_person_id` resolved from `assigned_by`), embeds `title`.
    - Inserts `Occasion` rows (dedupe by name via resolver-style exact match),
      links to people.
    - Commits. On any exception, rolls back and re-raises `PersistError`.

- [ ] **Step 1: Write the failing test** — `tests/test_persist.py`

```python
import datetime as dt
from tests.conftest import requires_db
from io_assistant.persist.writer import persist_store
from io_assistant.resolve.resolver import EntityResolver
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedEvent, ExtractedOccasion)
from io_assistant.db import models as m

class StubEmbedder:
    def embed_one(self, t): return [0.0]*768
    def embed(self, ts): return [[0.0]*768 for _ in ts]

NOW = dt.datetime(2026, 9, 7, 18, 0, tzinfo=dt.timezone.utc)

def _arcadian() -> ExtractionResult:
    return ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95),
                ExtractedPerson(name="Eelian", confidence=0.9)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        occasions=[ExtractedOccasion(name="Nafay and Eelian's birthday", date_phrase=None, confidence=0.8)],
        events=[ExtractedEvent(description="went out to eat", when_phrase="today",
                               people=["Nafay","Eelian"], places=["Arcadian"],
                               occasions=["Nafay and Eelian's birthday"],
                               attributes={"meal":"dinner"}, confidence=0.9)])

@requires_db
def test_persists_event_with_links(db, config):
    res = EntityResolver(db, StubEmbedder(), config.resolver)
    out = persist_store(db, StubEmbedder(), res,
        utterance_text="I went out with Nafay to eat at Arcadian for his and Eelian's birthday",
        source="text", captured_at=NOW, extraction=_arcadian(), now=NOW,
        confidence_gate=config.resolver.confidence_gate_threshold)
    assert not out.gated and len(out.event_ids) == 1
    ev = db.get(m.Event, out.event_ids[0])
    assert ev.attributes["meal"] == "dinner"
    assert ev.occurred_at.date() == dt.date(2026, 9, 7)
    assert db.query(m.EventPerson).filter_by(event_id=ev.id).count() == 2
    assert db.query(m.EventPlace).filter_by(event_id=ev.id).count() == 1
    assert db.query(m.Person).filter(m.Person.canonical_name.in_(["Nafay","Eelian"])).count() == 2

@requires_db
def test_low_confidence_gates_and_keeps_only_utterance(db, config):
    ext = _arcadian()
    ext.events[0].confidence = 0.3
    out = persist_store(db, StubEmbedder(),
        EntityResolver(db, StubEmbedder(), config.resolver),
        utterance_text="mumble arcadian something", source="text", captured_at=NOW,
        extraction=ext, now=NOW, confidence_gate=0.6)
    assert out.gated and "low confidence" in " ".join(out.gate_reasons).lower()
    assert db.query(m.Event).count() == 0
    assert db.get(m.Utterance, out.utterance_id) is not None

@requires_db
def test_confirmed_bypasses_gate(db, config):
    ext = _arcadian(); ext.events[0].confidence = 0.3
    out = persist_store(db, StubEmbedder(),
        EntityResolver(db, StubEmbedder(), config.resolver),
        utterance_text="x", source="text", captured_at=NOW, extraction=ext, now=NOW,
        confidence_gate=0.6, confirmed=True)
    assert not out.gated and len(out.event_ids) == 1
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement `io_assistant/persist/writer.py`** per the Interfaces block.

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Commit**

```bash
git add io_assistant/persist/ tests/test_persist.py
git commit -m "feat: persist_store transaction with confirmation gate"
```

---

## Task 14: Backend factory

**Files:**
- Create: `io_assistant/backend/hybrid.py`, `io_assistant/backend/factory.py`
- Test: `tests/test_backend_factory.py`

**Interfaces:**
- Consumes: `Config`, `LocalBackend`, `AnthropicBackend`.
- Produces:
  - `io_assistant.backend.hybrid.HybridBackend(local: Backend, cloud: Backend)` —
    `route` → local; `extract`, `plan`, `phrase` → cloud.
  - `io_assistant.backend.factory.build_backend(config: Config) -> Backend`:
    - `"local"` → `LocalBackend(config)`
    - `"anthropic"` → `AnthropicBackend(config)`
    - `"hybrid"` → `HybridBackend(LocalBackend(config), AnthropicBackend(config))`

- [ ] **Step 1: Write the failing test** — `tests/test_backend_factory.py`

```python
from io_assistant.backend.factory import build_backend
from io_assistant.backend.local import LocalBackend
from io_assistant.backend.hybrid import HybridBackend

def test_local(config):
    assert isinstance(build_backend(config), LocalBackend)

def test_hybrid(config):
    config.backend.provider = "hybrid"
    b = build_backend(config)
    assert isinstance(b, HybridBackend)

def test_hybrid_routes_split(config):
    class L:
        def route(self, u): return "store"
        def extract(self, *a): return "LOCAL"
        def plan(self, *a): ...
        def phrase(self, *a): ...
    class C:
        def route(self, u): return "query"
        def extract(self, *a): return "CLOUD"
        def plan(self, *a): ...
        def phrase(self, *a): ...
    from io_assistant.backend.hybrid import HybridBackend
    h = HybridBackend(L(), C())
    assert h.route("x") == "store"
    assert h.extract("x", None) == "CLOUD"
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement `hybrid.py` and `factory.py`.**

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Commit**

```bash
git add io_assistant/backend/hybrid.py io_assistant/backend/factory.py tests/test_backend_factory.py
git commit -m "feat: HybridBackend and backend factory"
```

---

## Task 15: Orchestrator STORE path + CLI

**Files:**
- Create: `io_assistant/orchestrator.py`, `io_assistant/cli.py`
- Test: `tests/test_orchestrator_store.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `io_assistant.orchestrator.Orchestrator(config, session_factory, backend=None)`
    — builds `backend` via the factory if not injected; builds `Embedder`.
  - `handle(self, text: str, *, source: str = "text", captured_at: datetime | None = None,
      confirmed: bool = False) -> HandleResult`
    where `HandleResult` (dataclass): `intent: Intent`, `stored: PersistResult | None`,
    `message: str` (human-readable summary for the CLI / future UI).
    - `intent == "unknown"` → message "I didn't understand that — try rephrasing."
    - `intent == "query"` → message "Query answering isn't available yet (Plan 2)."
      (no crash — this plan is storage only).
    - `intent == "store"`:
      - `Extractor.run` → `None` → insert utterance with `marker="extraction_failed"`,
        message says so.
      - gated → message lists `gate_reasons` and says "reply 'yes' to confirm".
      - stored → message summarizes what was written
        ("Stored: 1 event, people: Nafay, Eelian; place: Arcadian").
  - `io_assistant.cli.app` — a Typer app:
    - `io store "<text>"` → runs `handle`, prints `message`.
    - `io repl` → reads lines; if the previous result was gated and the line is
      `y`/`yes`, re-runs the previous text with `confirmed=True`.
    - `io doctor` → stub that prints "not implemented (Plan 4)" and exits 0.

- [ ] **Step 1: Write the failing test** — `tests/test_orchestrator_store.py`

```python
import datetime as dt
from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedEvent)
from io_assistant.db.base import make_engine, make_session_factory
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 7, 18, 0, tzinfo=dt.timezone.utc)

@requires_db
def test_store_path_writes_event(db, engine, config, fake_backend, monkeypatch):
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        events=[ExtractedEvent(description="dinner", when_phrase="today",
                               people=["Nafay"], places=["Arcadian"], confidence=0.9)]))
    # embedder stub so no Ollama needed
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0]*768,
        "embed": lambda self, ts: [[0.0]*768 for _ in ts]})())
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("I had dinner with Nafay at Arcadian", captured_at=NOW)
    assert res.intent == "store" and res.stored and len(res.stored.event_ids) == 1
    assert "Nafay" in res.message
    assert db.query(m.Event).count() == 1

@requires_db
def test_unknown_intent_message(db, config, fake_backend):
    fake_backend.set_intent("unknown")
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("asdfgh")
    assert res.intent == "unknown" and "rephrase" in res.message.lower()

@requires_db
def test_extraction_failure_marks_utterance(db, config, fake_backend, monkeypatch):
    fake_backend.set_intent("store")
    def boom(*a, **k): 
        from io_assistant.backend.local import BackendParseError
        raise BackendParseError("nope")
    fake_backend.extract = boom
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0]*768, "embed": lambda self, ts: [[0.0]*768]})())
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("something mumbled")
    assert db.query(m.Utterance).filter_by(marker="extraction_failed").count() == 1
```

- [ ] **Step 2: Run to verify it fails**

- [ ] **Step 3: Implement `io_assistant/orchestrator.py`** then `io_assistant/cli.py`.

- [ ] **Step 4: Run to verify it passes** → PASS

- [ ] **Step 5: Manual smoke** (executor, with Postgres + Ollama up):

```bash
uv run alembic upgrade head
uv run io store "I went out with Nafay to eat at Arcadian for his and Eelian's birthday"
```

Expected: prints a "Stored: 1 event ..." summary. Verify rows with `psql`.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/orchestrator.py io_assistant/cli.py tests/test_orchestrator_store.py
git commit -m "feat: orchestrator STORE path and CLI"
```

---

## Task 16: End-to-end scenario 1 + local-first socket guard

**Files:**
- Create: `tests/test_e2e_store.py`
- Modify: `.claude/state/completed.md`, `.claude/state/backlog.md`, `.claude/state/session.md`

**Interfaces:**
- Consumes: `Orchestrator`, fixtures.
- Produces: the acceptance test for Plan 1.

- [ ] **Step 1: Write the test** — `tests/test_e2e_store.py`

```python
import datetime as dt
import socket
import pytest
from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 7, 18, 0, tzinfo=dt.timezone.utc)

@requires_db
def test_arcadian_scenario_with_fake_backend(db, config, fake_backend, monkeypatch):
    from io_assistant.models_domain import (
        ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedEvent, ExtractedOccasion)
    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95),
                ExtractedPerson(name="Eelian", confidence=0.92)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        occasions=[ExtractedOccasion(name="Nafay and Eelian's birthday",
                                     date_phrase=None, confidence=0.8)],
        events=[ExtractedEvent(description="went out to eat", when_phrase="today",
                               people=["Nafay","Eelian"], places=["Arcadian"],
                               occasions=["Nafay and Eelian's birthday"],
                               attributes={"meal":"dinner"}, confidence=0.9)]))
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0]*768,
        "embed": lambda self, ts: [[0.0]*768 for _ in ts]})())
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("I went out with Nafay to eat at Arcadian for his and Eelian's birthday",
                   captured_at=NOW)
    assert res.stored and len(res.stored.event_ids) == 1
    ev = db.get(m.Event, res.stored.event_ids[0])
    assert ev.occurred_at.date() == dt.date(2026, 9, 7)
    people = {ep.person_id for ep in db.query(m.EventPerson).filter_by(event_id=ev.id)}
    assert len(people) == 2
    assert db.query(m.EventPlace).filter_by(event_id=ev.id).count() == 1
    assert db.query(m.EventOccasion).filter_by(event_id=ev.id).count() == 1

def test_local_first_no_foreign_sockets(config, monkeypatch):
    """LocalBackend + Embedder must only ever connect to localhost."""
    real_connect = socket.socket.connect
    def guard(self, address):
        host = address[0] if isinstance(address, tuple) else address
        assert host in ("127.0.0.1", "::1", "localhost"), f"foreign socket: {host}"
        return real_connect(self, address)
    monkeypatch.setattr(socket.socket, "connect", guard)
    # constructing the local backend + embedder must not dial out
    from io_assistant.backend.factory import build_backend
    build_backend(config)
```

- [ ] **Step 2: Run the full suite**

Run: `uv run pytest -v`
Expected: all non-opt-in tests PASS; `ollama`/`anthropic` tests skipped.

- [ ] **Step 3: Run the opt-in real-model suite once** (executor, manual):

```bash
IO_OLLAMA_TESTS=1 uv run pytest -m ollama -v
```

Expected: extractor + router fixture tests pass at the documented thresholds.
If the `light`-profile model is too weak, note it in
`.claude/knowledge/model-backends.md` and `docs/superpowers/specs` open-questions —
do not lower the assertions silently.

- [ ] **Step 4: Update state files**

- Move "Plan 1: core storage pipeline" to `completed.md` with today's date.
- `session.md` → "Plan 1 complete. Next: Plan 2 (query pipeline)."

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_store.py .claude/state/
git commit -m "test: end-to-end Arcadian store scenario and local-first socket guard"
```

---

## Self-Review

**Spec coverage (Plan 1 scope = spec stages 1–8):**
- Environment setup (user asked for it explicitly) → Task 0.
- Stage 1 scaffold → Task 1. Stage 1 `.claude` → Task 2.
- Stage 2 DB + migration → Task 3.
- Stage 3 backend abstraction → Tasks 4, 6, 7, 14; `embed()` → Task 5.
- Stage 4 persistence → Task 13.
- Stage 5 resolver → Tasks 11 (dates), 12 (resolver).
- Stage 6 extractor → Tasks 8 (schema), 9 (extractor).
- Stage 7 router → Task 10.
- Stage 8 STORE e2e → Tasks 15, 16.
- Spec §13 resource budget: `num_thread` cap + `keep_alive` + on-demand load in
  Task 6; profile→model mapping in Task 1; documented in Task 2's
  `resource-budget.md`. `OLLAMA_MAX_LOADED_MODELS`/`OLLAMA_NUM_PARALLEL` are
  environment settings for the Ollama process, documented in `run-local.md`
  (Task 2 Step 7) — not set by IO.
- Spec §13 embeddings-always-local → Task 5 + the Task 12 note.
- Spec §10 rules files → Task 2.

**Placeholder scan:** the `.claude/knowledge/*` files in Task 2 Step 6 are
described by content source rather than transcribed — acceptable because they are
summaries of a spec that travels with this plan, and the exact prose is not
load-bearing for later tasks. Everything code-bearing has real code.

**Type consistency:** `ExtractionResult` field names are fixed in Task 4 and used
identically in Tasks 6–9, 13, 15, 16. `ResolveOutcome` / `PersistResult` /
`HandleResult` dataclass field names are defined once (Tasks 12, 13, 15) and
matched in tests. `BackendParseError` appears in two modules (Tasks 6, 7); Task 9
explicitly addresses the duplication and offers a hoist — the executor must pick
one option and update imports consistently.

**Known ordering wrinkle:** Task 6 (`LocalBackend`) imports from
`io_assistant.extract.schema`, created in Task 8. Task 6 Step 5 calls for a stub
module first. If executing out of order, do Task 8 before Task 6.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-07-io-phase-1-core-storage.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
