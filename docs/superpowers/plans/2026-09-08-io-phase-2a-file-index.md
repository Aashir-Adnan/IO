# Phase 2A — File Index & Text Exploration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give IO read access to files under user-approved locations and a
persistent, graph-shaped index so repeat searches cost almost no model tokens.

**Architecture:** A new `io_assistant/files/` package mirrors the existing
`query/` pipeline: deterministic discovery (SQL FTS + pgvector KNN + entity
lookup + one-hop graph traversal) → deterministic ranking → a single model call
to phrase the answer. Every file is read, chunked, embedded, and summarised
exactly once; a content-hash gate makes re-indexing a no-op. A new coarse
router intent `file` is split into *register* vs *search* by deterministic code.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x + Alembic, `psycopg` 3, `pgvector`,
Postgres FTS (`tsvector`), `pydantic` v2, FastAPI, `typer`, `rapidfuzz` (already
a dep), new deps `pypdf` + `python-docx`. Embeddings via the local Ollama
`Embedder`. Model calls via the `Backend` interface (`FakeBackend` in tests).

**Spec:** `docs/superpowers/specs/2026-09-08-io-phase-2-file-index-design.md`
(read it alongside this plan). Media gallery / captioning is a separate spec
(`…-io-phase-2-media-library-design.md`) built after this.

## Global Constraints

Copied verbatim from the spec — every task inherits these:

- **local-first:** no new outbound network traffic. Only sanctioned non-local
  call remains `api.anthropic.com` when `backend.provider` is `anthropic`/
  `hybrid`. `tests/test_e2e_store.py`'s socket guard must stay green.
- **File text may reach the cloud** (user decision): when `backend.provider !=
  "local"`, `summarize_file` / `answer_from_files` send file text to Anthropic.
  The `[files]` config comment and `io files add` must say so. **Embeddings are
  always local**, every backend.
- **llm-boundaries:** the model never emits SQL, never ranks, never decides
  which file answers. Discovery, ranking, freshness, entity identity, and edge
  construction are deterministic Python.
- **migrations:** Alembic only. `embedding_dim` stays `768` (`db.models.EMBED_DIM`).
- **resource-budget:** the background index worker is single-threaded
  (concurrency 1), on demand. No background crawl of allowlist roots.
- **test-discipline:** TDD; never mock the database (real PostgreSQL at
  `IO_TEST_DATABASE_URL`); model calls use `FakeBackend`; embeddings use
  `StubEmbedder`.
- Package is `io_assistant` (never `io`). Everything runs via `uv run`.
- Windows-first dev: `.\dev.ps1 test [args]` runs the suite; `IO_TEST_DATABASE_URL`
  = `postgresql+psycopg://io:io@localhost:5432/io_test`.

## File Structure

**New package `io_assistant/files/`:**

| file | responsibility |
|---|---|
| `paths.py` | `AccessGate` — the single authority every filesystem read passes through. `AccessDenied`. |
| `walk.py` | `walk_dir()` — bounded directory discovery honouring excludes / symlinks / extensions. `FoundPath`, `RegistrationTooLarge`. |
| `extract.py` | `read_document()` — per-type text extraction (txt/md/pdf/docx/rtf/html/csv/…). `ExtractedDoc`. |
| `chunk.py` | `chunk_text()` — deterministic paragraph-aware chunker. |
| `store.py` | `FileIndex` — all DB reads/writes on the four file tables + graph traversal. `RegisterResult`. |
| `index.py` | `FileIndexer` — index one path: hash-gate → read → chunk → embed → summarise → post-process entities/references/edges. |
| `command.py` | `classify_file_command()`, `resolve_register_target()` — deterministic register-vs-search + path/phrase resolution. |
| `search.py` | `FileSearcher` — discover → rank → freshness → phrase. `FileAnswer`. |
| `cards.py` | `files_card()` — `FileAnswer` → `FilesCard`. |
| `queue.py` | `IndexQueue` — the service's single-thread background index worker. |

**Modified:**

| file | change |
|---|---|
| `io_assistant/db/models.py` | append `FileNode`, `FileChunk`, `FileEdge`, `FileEntityLink` |
| `io_assistant/db/migrations/versions/0004_file_index.py` | **new** migration |
| `io_assistant/config.py` | `FilesConfig`; `files: FilesConfig` on `Config` |
| `config.toml` | `[files]` block |
| `io_assistant/models_domain.py` | `Intent` += `"file"`; `FileHit`, `FilesCard`; `Card` union |
| `io_assistant/backend/interface.py` | `Backend` Protocol += `summarize_file`, `answer_from_files` |
| `io_assistant/backend/{local,anthropic_backend,hybrid}.py` | implement both |
| `io_assistant/prompts/file_summary.txt`, `file_answer.txt` | **new** |
| `io_assistant/prompts/route.txt` | add the `FILE` class + examples |
| `io_assistant/orchestrator.py` | `file` branch, `_file_register`, `_file_search` |
| `io_assistant/service/app.py` | `/files*` routes + `IndexQueue` startup |
| `io_assistant/service/schemas.py` | file request/response models |
| `io_assistant/cli.py` | `io files` sub-app |
| `frontend/views/files.js`, `components/card.js`, `vendor/icons.js`, `app.js`, `app.css` | Files view + `files` card + text viewer |
| `tests/conftest.py` | `StubEmbedder` + `stub_embedder` fixture; `FakeBackend` += the two methods; `config` fixture += `files=FilesConfig()` |
| `tests/fixtures/files/` | `notes.md`, `data.csv`, `sample.pdf`, `sample.docx`, `binary.bin` |
| `.claude/knowledge/file-index.md` | **new** |
| `.claude/knowledge/data-model.md` | note `file` intent + the four tables |
| `.claude/state/{session,completed,backlog}.md` | update |

**Dependencies to add (Task 4):** `uv add pypdf python-docx`.

---

## Task 1: Schema, config, domain types

**Files:**
- Modify: `io_assistant/config.py` (after `UiConfig`, ~line 62)
- Modify: `config.toml` (append `[files]`)
- Modify: `io_assistant/db/models.py` (append after `Message`, ~line 210; add
  `Boolean`, `Computed` to the `sqlalchemy` import; `TSVECTOR` from
  `sqlalchemy.dialects.postgresql`)
- Modify: `io_assistant/models_domain.py` (`Intent` line 9; append cards after
  `SourcesCard` ~line 113; `Card` union line 116)
- Create: `io_assistant/db/migrations/versions/0004_file_index.py`
- Modify: `tests/conftest.py` (`config` fixture ~line 20; add `StubEmbedder`
  + `stub_embedder` fixture near the other fakes ~line 195)
- Test: `tests/test_files_schema.py`

**Interfaces:**
- Produces:
  - `FilesConfig` (pydantic) with fields exactly as in spec §4; `Config.files:
    FilesConfig = FilesConfig()`.
  - ORM `FileNode` (`file_nodes`), `FileChunk` (`file_chunks`), `FileEdge`
    (`file_edges`), `FileEntityLink` (`file_entity_links`) — columns per spec
    §3. Key column names later tasks use: `FileNode.id`, `.path`, `.path_key`,
    `.parent_key`, `.kind`, `.mime`, `.media_kind`, `.size_bytes`,
    `.content_hash`, `.mtime`, `.registered_at`, `.registered_root`,
    `.indexed_at`, `.index_hash`, `.title`, `.summary`, `.status`, `.error`,
    `.embedding`. `FileChunk.file_id/.ord/.text/.token_estimate/.embedding/.tsv`.
    `FileEdge.src_id/.dst_id/.rel/.detail`. `FileEntityLink.file_id/.etype/
    .entity_id/.mentions/.source`.
  - `models_domain.Intent = Literal["store","query","file","unknown"]`.
  - `models_domain.FileHit(path: str, title: str | None, why: str, media_kind:
    str | None = None)`.
  - `models_domain.FilesCard(type: Literal["files"]="files", hits:
    list[FileHit], searched: int = 0)`; `Card = RecordCard | TaskListCard |
    SourcesCard | FilesCard`.
  - `tests/conftest.py::StubEmbedder(mapping: dict | None = None)` with
    `embed_one(t) -> list[float]` and `embed(ts) -> list[list[float]]` (768-d,
    zeros by default); `stub_embedder` fixture returning `StubEmbedder()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_schema.py
from tests.conftest import requires_db
from io_assistant.config import FilesConfig, load_config
from io_assistant.db import models as m
from io_assistant.models_domain import Intent, FilesCard, FileHit, Card


def test_files_config_defaults():
    c = FilesConfig()
    assert c.enabled is False
    assert c.max_file_bytes == 2_000_000
    assert ".pdf" in c.index_extensions
    assert ".jpg" in c.media_extensions
    assert any("node_modules" in g for g in c.exclude_globs)
    assert c.retrieval_file_limit == 6


def test_config_has_files_block():
    assert isinstance(load_config().files, FilesConfig)


def test_intent_includes_file():
    assert "file" in getattr(Intent, "__args__", ())


def test_files_card_shape():
    card = FilesCard(hits=[FileHit(path="/x/a.md", title="A", why="matches x")])
    assert card.type == "files"
    assert card.model_dump()["hits"][0]["path"] == "/x/a.md"


@requires_db
def test_file_tables_exist(db):
    n = m.FileNode(path="/tmp/a.md", path_key="/tmp/a.md", kind="file",
                   status="pending")
    db.add(n)
    db.flush()
    assert n.id is not None
    db.add(m.FileChunk(file_id=n.id, ord=0, text="hello world",
                       token_estimate=2, embedding=[0.0] * 768))
    db.add(m.FileEdge(src_id=n.id, dst_id=n.id, rel="contains"))
    db.add(m.FileEntityLink(file_id=n.id, etype="person", entity_id=1))
    db.flush()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_files_schema.py -q`
Expected: FAIL — `ImportError: cannot import name 'FilesConfig'`.

- [ ] **Step 3: Add `FilesConfig` and wire it into `Config`**

```python
# io_assistant/config.py  — after class UiConfig
class FilesConfig(BaseModel):
    enabled: bool = False
    allowlist_roots: list[str] = []
    max_file_bytes: int = 2_000_000
    index_extensions: list[str] = [
        ".txt", ".md", ".markdown", ".rst", ".pdf", ".docx", ".rtf",
        ".csv", ".tsv", ".json", ".yaml", ".yml", ".html", ".htm", ".xml", ".log",
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rb", ".rs",
        ".c", ".h", ".cpp", ".sh",
    ]
    media_extensions: list[str] = [
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tiff",
        ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi",
    ]
    exclude_globs: list[str] = [
        "**/.git/**", "**/node_modules/**", "**/__pycache__/**", "**/.venv/**",
        "**/.env*", "**/*.env", "**/*.pem", "**/*.key", "**/id_rsa*",
        "**/*.kdbx", "**/*.ppk", "**/.ssh/**", "**/.aws/**", "**/.gnupg/**",
    ]
    chunk_tokens: int = 400
    chunk_overlap: int = 40
    max_chunks_per_file: int = 60
    max_files_per_registration: int = 5000
    retrieval_file_limit: int = 6
    follow_symlinks: bool = False
    thumbs_dir: str = "~/.local/share/io/thumbs"
```

Add to `class Config`: `files: FilesConfig = FilesConfig()`.
(Pydantic v2 mutable defaults on a `BaseModel` field are deep-copied per
instance — matching how `service`/`voice`/`ui` are already declared.)

- [ ] **Step 4: Append the `[files]` block to `config.toml`**

```toml
[files]
# IO can read files under these locations and any path you register.
# NOTE: when [backend].provider is "anthropic" or "hybrid", file text is sent
# to api.anthropic.com for summarising and answering. Embeddings stay local.
enabled = false
allowlist_roots = []
max_file_bytes = 2000000
```

- [ ] **Step 5: Add `Intent` member + the file cards to `models_domain.py`**

```python
Intent = Literal["store", "query", "file", "unknown"]
```

```python
# after class SourcesCard
class FileHit(BaseModel):
    path: str
    title: str | None = None
    why: str
    media_kind: str | None = None


class FilesCard(BaseModel):
    type: Literal["files"] = "files"
    hits: list[FileHit] = Field(default_factory=list)
    searched: int = 0


Card = RecordCard | TaskListCard | SourcesCard | FilesCard
```

- [ ] **Step 6: Append the four ORM models to `db/models.py`**

Extend imports: `Boolean`, `Computed` from `sqlalchemy`; add
`from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR`.

```python
class FileNode(Base):
    __tablename__ = "file_nodes"
    __table_args__ = (
        Index("ix_file_nodes_path_key", "path_key", unique=True),
        Index("ix_file_nodes_parent_key", "parent_key"),
        Index("ix_file_nodes_content_hash", "content_hash"),
        Index("ix_file_nodes_status", "status"),
        Index("ix_file_nodes_media_kind", "media_kind"),
        Index("ix_file_nodes_registered_root", "registered_root",
              postgresql_where=text("registered_root")),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    path_key: Mapped[str] = mapped_column(Text, nullable=False)
    parent_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)  # file|dir
    mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    media_kind: Mapped[str | None] = mapped_column(String(8), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mtime: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    captured_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registered_root: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    indexed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    index_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class FileChunk(Base):
    __tablename__ = "file_chunks"
    __table_args__ = (
        Index("ix_file_chunks_file_id_ord", "file_id", "ord", unique=True),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False)
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    token_estimate: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=False)
    tsv = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english', text)", persisted=True),
    )


class FileEdge(Base):
    __tablename__ = "file_edges"
    __table_args__ = (
        Index("ix_file_edges_src_rel", "src_id", "rel"),
        Index("ix_file_edges_dst_rel", "dst_id", "rel"),
        Index("ix_file_edges_uniq", "src_id", "dst_id", "rel", unique=True),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    src_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False)
    dst_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False)
    rel: Mapped[str] = mapped_column(String(16), nullable=False)  # contains|references
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileEntityLink(Base):
    __tablename__ = "file_entity_links"
    __table_args__ = (
        Index("ix_file_entity_links_uniq", "file_id", "etype", "entity_id", unique=True),
        Index("ix_file_entity_links_entity", "etype", "entity_id"),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False)
    etype: Mapped[str] = mapped_column(String(8), nullable=False)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mentions: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="summary")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 7: Write the migration `0004_file_index.py`**

```python
"""file index: nodes, chunks, edges, entity links

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = 768


def upgrade() -> None:
    op.create_table(
        "file_nodes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("path_key", sa.Text(), nullable=False),
        sa.Column("parent_key", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("mime", sa.String(128), nullable=True),
        sa.Column("media_kind", sa.String(8), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column("mtime", sa.DateTime(timezone=True), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_root", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("index_hash", sa.String(64), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_file_nodes_path_key", "file_nodes", ["path_key"], unique=True)
    op.create_index("ix_file_nodes_parent_key", "file_nodes", ["parent_key"])
    op.create_index("ix_file_nodes_content_hash", "file_nodes", ["content_hash"])
    op.create_index("ix_file_nodes_status", "file_nodes", ["status"])
    op.create_index("ix_file_nodes_media_kind", "file_nodes", ["media_kind"])
    op.create_index("ix_file_nodes_registered_root", "file_nodes",
                    ["registered_root"],
                    postgresql_where=sa.text("registered_root"))

    op.create_table(
        "file_chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("file_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ord", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(),
                  sa.Computed("to_tsvector('english', text)", persisted=True)),
    )
    op.create_index("ix_file_chunks_file_id_ord", "file_chunks",
                    ["file_id", "ord"], unique=True)
    op.execute("CREATE INDEX ix_file_chunks_tsv ON file_chunks USING gin (tsv)")

    op.create_table(
        "file_edges",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("src_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dst_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rel", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_file_edges_src_rel", "file_edges", ["src_id", "rel"])
    op.create_index("ix_file_edges_dst_rel", "file_edges", ["dst_id", "rel"])
    op.create_index("ix_file_edges_uniq", "file_edges",
                    ["src_id", "dst_id", "rel"], unique=True)

    op.create_table(
        "file_entity_links",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("file_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("etype", sa.String(8), nullable=False),
        sa.Column("entity_id", sa.BigInteger(), nullable=False),
        sa.Column("mentions", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(8), nullable=False, server_default="summary"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_file_entity_links_uniq", "file_entity_links",
                    ["file_id", "etype", "entity_id"], unique=True)
    op.create_index("ix_file_entity_links_entity", "file_entity_links",
                    ["etype", "entity_id"])

    op.execute(
        "CREATE INDEX ix_file_nodes_embedding ON file_nodes "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX ix_file_chunks_embedding ON file_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.drop_table("file_entity_links")
    op.drop_table("file_edges")
    op.drop_table("file_chunks")
    op.drop_table("file_nodes")
```

- [ ] **Step 8: Update `tests/conftest.py`**

Add `files=FilesConfig()` to the `config` fixture's `Config(...)` call (and
`from io_assistant.config import ..., FilesConfig`).

Add near the other fakes:

```python
class StubEmbedder:
    """Deterministic embedder for tests — 768-d zeros unless a mapping hit."""

    def __init__(self, mapping: dict | None = None):
        self.mapping = mapping or {}
        self.calls: list[str] = []

    def embed_one(self, t: str) -> list[float]:
        self.calls.append(t)
        return self.mapping.get(t, [0.0] * 768)

    def embed(self, ts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in ts]


@pytest.fixture
def stub_embedder():
    return StubEmbedder()
```

- [ ] **Step 9: Run the tests**

Run: `.\dev.ps1 test tests/test_files_schema.py tests/test_config.py tests/test_backend_interface.py -q`
Expected: PASS. The session-scoped `engine` fixture rebuilds the schema through
`alembic upgrade head`, so a green `test_file_tables_exist` proves `0004`
applies and downgrades.

- [ ] **Step 10: Commit**

```bash
git add io_assistant/config.py config.toml io_assistant/db/models.py \
  io_assistant/db/migrations/versions/0004_file_index.py \
  io_assistant/models_domain.py tests/conftest.py tests/test_files_schema.py
git commit -m "feat(files): 0004 file-index schema, FilesConfig, file intent + card"
```

---

## Task 2: `paths.py` — the access gate

**Files:**
- Create: `io_assistant/files/__init__.py` (empty)
- Create: `io_assistant/files/paths.py`
- Test: `tests/test_files_paths.py`

**Interfaces:**
- Consumes: `FilesConfig` (Task 1).
- Produces:
  - `AccessDenied(path: str, reason: str)` — `Exception`.
  - `AccessGate(config: FilesConfig)`:
    - `.roots: list[Path]` — expanded, resolved `allowlist_roots` (non-existent
      ones dropped).
    - `resolve(raw: str) -> Path` — `expanduser` → `Path(raw)` →
      `.resolve(strict=False)`. Raises `AccessDenied` if the parent chain does
      not exist at all.
    - `key(path: Path) -> str` — `str(path).lower()` on Windows (`os.name ==
      "nt"`), `str(path)` otherwise.
    - `is_allowed(path: Path, *, registered_keys: set[str]) -> bool`.
    - `assert_allowed(path: Path, *, registered_keys: set[str]) -> None` —
      raises `AccessDenied` with a specific reason otherwise.
    - `is_excluded(path: Path) -> bool` — any `exclude_globs` pattern matches
      the path's posix string (case-insensitive).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_paths.py
import os
import pytest
from pathlib import Path
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate, AccessDenied


def _gate(tmp_path, **kw):
    return AccessGate(FilesConfig(allowlist_roots=[str(tmp_path / "allowed")], **kw))


def test_allowlist_root_is_allowed(tmp_path):
    (tmp_path / "allowed").mkdir()
    f = tmp_path / "allowed" / "a.md"
    f.write_text("x")
    g = _gate(tmp_path)
    assert g.is_allowed(f, registered_keys=set())


def test_outside_everything_is_denied(tmp_path):
    (tmp_path / "allowed").mkdir()
    f = tmp_path / "elsewhere" / "secret.md"
    g = _gate(tmp_path)
    assert not g.is_allowed(f, registered_keys=set())


def test_registered_ancestor_authorises_descendant(tmp_path):
    root = tmp_path / "proj"
    (root / "sub").mkdir(parents=True)
    f = root / "sub" / "notes.md"
    f.write_text("x")
    g = _gate(tmp_path)
    assert g.is_allowed(f, registered_keys={g.key(root)})


def test_excluded_glob_denied_even_inside_allowlist(tmp_path):
    (tmp_path / "allowed" / "node_modules").mkdir(parents=True)
    f = tmp_path / "allowed" / "node_modules" / "x.js"
    f.write_text("x")
    g = _gate(tmp_path)
    assert not g.is_allowed(f, registered_keys=set())


def test_env_file_denied(tmp_path):
    (tmp_path / "allowed").mkdir()
    f = tmp_path / "allowed" / ".env"
    f.write_text("SECRET=1")
    g = _gate(tmp_path)
    assert not g.is_allowed(f, registered_keys=set())


@pytest.mark.skipif(os.name == "nt", reason="symlink perms on Windows")
def test_symlink_denied_unless_allowed(tmp_path):
    (tmp_path / "allowed").mkdir()
    target = tmp_path / "outside.md"
    target.write_text("x")
    link = tmp_path / "allowed" / "link.md"
    link.symlink_to(target)
    assert not _gate(tmp_path).is_allowed(link, registered_keys=set())
    assert _gate(tmp_path, follow_symlinks=True).is_allowed(link, registered_keys=set())


def test_assert_allowed_raises_with_reason(tmp_path):
    (tmp_path / "allowed").mkdir()
    g = _gate(tmp_path)
    with pytest.raises(AccessDenied):
        g.assert_allowed(tmp_path / "nope" / "x.md", registered_keys=set())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_files_paths.py -q`
Expected: FAIL — `ModuleNotFoundError: io_assistant.files.paths`.

- [ ] **Step 3: Implement `paths.py`**

```python
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from io_assistant.config import FilesConfig

__all__ = ["AccessGate", "AccessDenied"]

_WIN = os.name == "nt"


class AccessDenied(Exception):
    def __init__(self, path: str, reason: str):
        super().__init__(f"{reason}: {path}")
        self.path = path
        self.reason = reason


class AccessGate:
    def __init__(self, config: FilesConfig):
        self._cfg = config
        self._excludes = list(config.exclude_globs)
        self.roots: list[Path] = []
        for r in config.allowlist_roots:
            p = Path(os.path.expanduser(r)).resolve(strict=False)
            if p.exists():
                self.roots.append(p)

    # --- helpers -----------------------------------------------------------
    def resolve(self, raw: str) -> Path:
        p = Path(os.path.expanduser(raw)).resolve(strict=False)
        # walk up to the first existing ancestor; if none, the path is bogus
        probe = p
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        if not probe.exists():
            raise AccessDenied(str(p), "path does not resolve")
        return p

    def key(self, path: Path) -> str:
        s = str(path)
        return s.lower() if _WIN else s

    def _ancestors_keys(self, path: Path) -> set[str]:
        return {self.key(a) for a in path.parents}

    def is_excluded(self, path: Path) -> bool:
        s = path.as_posix()
        s_cmp = s.lower() if _WIN else s
        for pat in self._excludes:
            p = pat.lower() if _WIN else pat
            if fnmatch.fnmatch(s_cmp, p):
                return True
        return False

    def _is_symlink_escape(self, path: Path) -> bool:
        if self._cfg.follow_symlinks:
            return False
        probe = path
        while probe != probe.parent:
            if probe.is_symlink():
                return True
            probe = probe.parent
        return False

    # --- the gate --------------------------------------------------------
    def is_allowed(self, path: Path, *, registered_keys: set[str]) -> bool:
        try:
            self.assert_allowed(path, registered_keys=registered_keys)
            return True
        except AccessDenied:
            return False

    def assert_allowed(self, path: Path, *, registered_keys: set[str]) -> None:
        p = path if path.is_absolute() else path.resolve(strict=False)
        if self.is_excluded(p):
            raise AccessDenied(str(p), "matches an exclude pattern")
        if self._is_symlink_escape(p):
            raise AccessDenied(str(p), "symlink (follow_symlinks is off)")
        pk = self.key(p)
        if pk in registered_keys or (registered_keys & self._ancestors_keys(p)):
            return
        for root in self.roots:
            try:
                p.relative_to(root)
                return
            except ValueError:
                continue
        raise AccessDenied(str(p), "not under a registered path or allowlist root")
```

- [ ] **Step 4: Run the tests**

Run: `.\dev.ps1 test tests/test_files_paths.py -q`
Expected: PASS (7 passed, 1 skipped on Windows).

- [ ] **Step 5: Commit**

```bash
git add io_assistant/files/__init__.py io_assistant/files/paths.py tests/test_files_paths.py
git commit -m "feat(files): AccessGate — deny-by-default filesystem read authority"
```

---

## Task 3: `walk.py` — bounded directory discovery

**Files:**
- Create: `io_assistant/files/walk.py`
- Test: `tests/test_files_walk.py`

**Interfaces:**
- Consumes: `FilesConfig` (Task 1), `AccessGate` (Task 2).
- Produces:
  - `FoundPath` dataclass: `path: Path`, `kind: str` (`"file"`),
    `mime: str | None`, `media_kind: str | None`, `size: int`,
    `mtime: datetime` (aware UTC).
  - `RegistrationTooLarge(count: int, cap: int)` — `Exception`.
  - `walk_dir(root: Path, config: FilesConfig, gate: AccessGate) ->
    Iterator[FoundPath]` — yields files whose suffix is in
    `index_extensions ∪ media_extensions`, pruning excluded dirs and (unless
    `follow_symlinks`) symlinked entries, raising `RegistrationTooLarge` once
    the yielded count would exceed `max_files_per_registration`.
  - `classify_media(suffix: str, config) -> str | None` — `"image"` /
    `"video"` / `None` from the extension.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_walk.py
import pytest
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.walk import walk_dir, RegistrationTooLarge, classify_media


def _setup(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("a")
    (tmp_path / "notes" / "b.txt").write_text("b")
    (tmp_path / "notes" / "pic.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "notes" / "skip.bin").write_bytes(b"\x00")
    (tmp_path / "notes" / "node_modules").mkdir()
    (tmp_path / "notes" / "node_modules" / "x.js").write_text("x")
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    return cfg, AccessGate(cfg), tmp_path / "notes"


def test_walk_yields_supported_files_only(tmp_path):
    cfg, gate, root = _setup(tmp_path)
    got = {p.path.name for p in walk_dir(root, cfg, gate)}
    assert got == {"a.md", "b.txt", "pic.jpg"}


def test_walk_prunes_excluded_dirs(tmp_path):
    cfg, gate, root = _setup(tmp_path)
    assert all("node_modules" not in str(p.path) for p in walk_dir(root, cfg, gate))


def test_walk_sets_media_kind(tmp_path):
    cfg, gate, root = _setup(tmp_path)
    by_name = {p.path.name: p for p in walk_dir(root, cfg, gate)}
    assert by_name["pic.jpg"].media_kind == "image"
    assert by_name["a.md"].media_kind is None


def test_walk_raises_when_over_cap(tmp_path):
    d = tmp_path / "many"
    d.mkdir()
    for i in range(12):
        (d / f"f{i}.txt").write_text("x")
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)], max_files_per_registration=10)
    with pytest.raises(RegistrationTooLarge):
        list(walk_dir(d, cfg, AccessGate(cfg)))


def test_classify_media():
    cfg = FilesConfig()
    assert classify_media(".mp4", cfg) == "video"
    assert classify_media(".PNG", cfg) == "image"
    assert classify_media(".md", cfg) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_files_walk.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `walk.py`**

```python
from __future__ import annotations

import datetime as dt
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate

__all__ = ["FoundPath", "RegistrationTooLarge", "walk_dir", "classify_media"]


@dataclass
class FoundPath:
    path: Path
    kind: str
    mime: str | None
    media_kind: str | None
    size: int
    mtime: dt.datetime


class RegistrationTooLarge(Exception):
    def __init__(self, count: int, cap: int):
        super().__init__(f"{count} files exceeds max_files_per_registration ({cap})")
        self.count = count
        self.cap = cap


def classify_media(suffix: str, config: FilesConfig) -> str | None:
    s = suffix.lower()
    if s not in {e.lower() for e in config.media_extensions}:
        return None
    return "video" if s in {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"} else "image"


def _mtime(p: Path) -> dt.datetime:
    return dt.datetime.fromtimestamp(p.stat().st_mtime, tz=dt.timezone.utc)


def walk_dir(root: Path, config: FilesConfig, gate: AccessGate) -> Iterator[FoundPath]:
    exts = {e.lower() for e in (*config.index_extensions, *config.media_extensions)}
    cap = config.max_files_per_registration
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=config.follow_symlinks):
        d = Path(dirpath)
        # prune excluded / symlinked subdirs in-place
        dirnames[:] = [
            name for name in dirnames
            if not gate.is_excluded(d / name)
            and (config.follow_symlinks or not (d / name).is_symlink())
        ]
        for name in filenames:
            p = d / name
            if p.suffix.lower() not in exts:
                continue
            if gate.is_excluded(p):
                continue
            if not config.follow_symlinks and p.is_symlink():
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            count += 1
            if count > cap:
                raise RegistrationTooLarge(count, cap)
            yield FoundPath(
                path=p, kind="file",
                mime=mimetypes.guess_type(p.name)[0],
                media_kind=classify_media(p.suffix, config),
                size=st.st_size,
                mtime=dt.datetime.fromtimestamp(st.st_mtime, tz=dt.timezone.utc),
            )
```

- [ ] **Step 4: Run the tests**

Run: `.\dev.ps1 test tests/test_files_walk.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/files/walk.py tests/test_files_walk.py
git commit -m "feat(files): walk_dir — bounded discovery with exclude pruning"
```

---

## Task 4: `extract.py` — per-type text extraction

**Files:**
- Create: `io_assistant/files/extract.py`
- Modify: `pyproject.toml` (deps) — run `uv add pypdf python-docx`
- Create fixtures: `tests/fixtures/files/notes.md`, `data.csv`, `binary.bin`,
  `sample.pdf`, `sample.docx` (generate the last two with a one-off script,
  see Step 3)
- Test: `tests/test_files_extract.py`

**Interfaces:**
- Consumes: `FilesConfig` (Task 1).
- Produces:
  - `ExtractedDoc` dataclass: `text: str`, `title: str | None`,
    `truncated: bool`, `status: str` (`"ok"` | `"too_large"` | `"unreadable"`),
    `error: str | None`.
  - `read_document(path: Path, config: FilesConfig) -> ExtractedDoc`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_extract.py
from pathlib import Path
from io_assistant.config import FilesConfig
from io_assistant.files.extract import read_document

FX = Path(__file__).parent / "fixtures" / "files"


def test_reads_markdown_with_title():
    d = read_document(FX / "notes.md", FilesConfig())
    assert d.status == "ok"
    assert "lease" in d.text.lower()
    assert d.title == "Apartment Notes"


def test_reads_csv_rows():
    d = read_document(FX / "data.csv", FilesConfig())
    assert d.status == "ok"
    assert "Granjur" in d.text


def test_reads_pdf():
    d = read_document(FX / "sample.pdf", FilesConfig())
    assert d.status == "ok"
    assert d.text.strip()


def test_reads_docx():
    d = read_document(FX / "sample.docx", FilesConfig())
    assert d.status == "ok"
    assert d.text.strip()


def test_binary_is_unreadable():
    d = read_document(FX / "binary.bin", FilesConfig())
    assert d.status == "unreadable"


def test_oversize_keeps_no_text(tmp_path):
    big = tmp_path / "big.txt"
    big.write_text("x" * 5000)
    d = read_document(big, FilesConfig(max_file_bytes=1000))
    assert d.status == "too_large"
    assert d.text == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_files_extract.py -q`
Expected: FAIL — `ModuleNotFoundError` / missing fixtures.

- [ ] **Step 3: Add deps + create fixtures**

```bash
uv add pypdf python-docx
```

`tests/fixtures/files/notes.md`:
```markdown
# Apartment Notes

The lease runs 12 months. Pets are allowed with a deposit.
Landlord: Mr. Khan.
```

`tests/fixtures/files/data.csv`:
```csv
vendor,amount,date
Granjur Technologies,1200,2026-08-01
City Power,64,2026-08-03
```

`tests/fixtures/files/binary.bin` — write raw bytes:
```bash
uv run python -c "open('tests/fixtures/files/binary.bin','wb').write(bytes(range(256))*4)"
```

Generate `sample.pdf` + `sample.docx` once and commit them:
```bash
uv run python - <<'PY'
from pypdf import PdfWriter
w = PdfWriter(); w.add_blank_page(width=200, height=200)
# pypdf can't add text; use reportlab-free route: write a minimal text PDF by hand
import pathlib
pathlib.Path("tests/fixtures/files/sample.pdf").write_bytes(
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 144]/Contents 4 0 R"
    b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 60>>stream\nBT /F1 18 Tf 20 100 Td (Lease agreement draft) Tj ET\nendstream endobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF")
from docx import Document
doc = Document(); doc.add_heading("Trip Plan", 0)
doc.add_paragraph("Hunza trip in June with Nafay. Budget 80k.")
doc.save("tests/fixtures/files/sample.docx")
PY
```
If the hand-rolled PDF does not parse under `pypdf`, install `reportlab` as a
**dev** dep (`uv add --group dev reportlab`) and generate a real one — but try
the minimal PDF first.

- [ ] **Step 4: Implement `extract.py`**

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from io_assistant.config import FilesConfig

__all__ = ["ExtractedDoc", "read_document"]

_HEAD_MD = re.compile(r"^#\s+(.+)$", re.M)
_HEAD_HTML = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_TAGS = re.compile(r"<[^>]+>")
_RTF = re.compile(r"\\[a-z]+-?\d* ?|[{}]")


@dataclass
class ExtractedDoc:
    text: str
    title: str | None
    truncated: bool
    status: str
    error: str | None = None


def _title_from(text: str, suffix: str) -> str | None:
    if suffix in (".md", ".markdown", ".rst"):
        m = _HEAD_MD.search(text)
        if m:
            return m.group(1).strip()
    if suffix in (".html", ".htm"):
        m = _HEAD_HTML.search(text)
        if m:
            return _TAGS.sub("", m.group(1)).strip()
    return None


def read_document(path: Path, config: FilesConfig) -> ExtractedDoc:
    try:
        size = path.stat().st_size
    except OSError as e:
        return ExtractedDoc("", None, False, "unreadable", str(e))
    if size > config.max_file_bytes:
        return ExtractedDoc("", None, False, "too_large", None)

    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n".join((pg.extract_text() or "") for pg in reader.pages)
            title = (reader.metadata.title if reader.metadata else None) or None
        elif suffix == ".docx":
            import docx

            doc = docx.Document(str(path))
            text = "\n".join(p.text for p in doc.paragraphs)
            title = doc.paragraphs[0].text.strip() if doc.paragraphs else None
        elif suffix in (".html", ".htm", ".xml"):
            raw = path.read_text(encoding="utf-8", errors="replace")
            title = _title_from(raw, suffix)
            text = re.sub(r"\s+\n", "\n", _TAGS.sub(" ", raw))
        elif suffix == ".rtf":
            raw = path.read_text(encoding="utf-8", errors="replace")
            text, title = _RTF.sub("", raw), None
        elif suffix in (".csv", ".tsv"):
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            text, title = "\n".join(lines[:200]), None
        else:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = path.read_bytes().decode("latin-1")
            title = _title_from(text, suffix)
    except Exception as e:  # pragma: no cover - defensive
        return ExtractedDoc("", None, False, "unreadable", f"{type(e).__name__}: {e}")

    text = text.strip()
    if not text:
        return ExtractedDoc("", title, False, "unreadable", "no extractable text")
    if title is None:
        title = path.stem
    return ExtractedDoc(text, title, False, "ok", None)
```

*(A file that decodes but is pure control bytes — like `binary.bin` — decodes
under latin-1 to a string; add a heuristic: if > 30 % of the first 2 kB are
non-printable, treat as `unreadable`.)* Add before the `text.strip()`:

```python
        sample = text[:2048]
        if sample and sum(c.isprintable() or c in "\r\n\t" for c in sample) / len(sample) < 0.7:
            return ExtractedDoc("", title, False, "unreadable", "binary content")
```

- [ ] **Step 5: Run the tests**

Run: `.\dev.ps1 test tests/test_files_extract.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock io_assistant/files/extract.py \
  tests/fixtures/files/ tests/test_files_extract.py
git commit -m "feat(files): read_document — text extraction for md/pdf/docx/html/csv"
```

---

## Task 5: `chunk.py` — the chunker

**Files:**
- Create: `io_assistant/files/chunk.py`
- Test: `tests/test_files_chunk.py`

**Interfaces:**
- Produces:
  - `chunk_text(text: str, *, chunk_tokens: int, overlap: int, max_chunks: int)
    -> list[str]` — paragraph-aware, ~`chunk_tokens` per chunk (1 token ≈ 4
    chars), `overlap` tokens of tail carried forward, single over-long
    paragraphs hard-split, stops at `max_chunks`. Pure, deterministic.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_chunk.py
from io_assistant.files.chunk import chunk_text


def test_short_text_is_one_chunk():
    assert chunk_text("hello world", chunk_tokens=400, overlap=40, max_chunks=60) == ["hello world"]


def test_empty_text_is_no_chunks():
    assert chunk_text("   ", chunk_tokens=400, overlap=40, max_chunks=60) == []


def test_splits_on_paragraphs_and_respects_size():
    para = ("word " * 300).strip()          # ~1500 chars ~ 375 tokens
    text = para + "\n\n" + para
    chunks = chunk_text(text, chunk_tokens=400, overlap=20, max_chunks=60)
    assert len(chunks) == 2
    assert all(len(c) <= 400 * 4 + 80 for c in chunks)


def test_hard_splits_a_giant_paragraph():
    giant = "x" * 5000
    chunks = chunk_text(giant, chunk_tokens=100, overlap=0, max_chunks=60)
    assert len(chunks) >= 12


def test_stops_at_max_chunks():
    text = "\n\n".join("para " + str(i) for i in range(100))
    assert len(chunk_text(text, chunk_tokens=1, overlap=0, max_chunks=5)) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_files_chunk.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `chunk.py`**

```python
from __future__ import annotations

import re

__all__ = ["chunk_text"]

_PARA = re.compile(r"\n\s*\n")


def _chars(tokens: int) -> int:
    return tokens * 4


def chunk_text(text: str, *, chunk_tokens: int, overlap: int, max_chunks: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    limit = _chars(chunk_tokens)
    ov = _chars(overlap)

    paras: list[str] = []
    for p in _PARA.split(text):
        p = p.strip()
        if not p:
            continue
        while len(p) > limit:
            paras.append(p[:limit])
            p = p[limit:]
        if p:
            paras.append(p)

    chunks: list[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + 2 + len(p) > limit:
            chunks.append(buf)
            if len(chunks) >= max_chunks:
                return chunks
            buf = (buf[-ov:] + "\n\n" + p) if ov else p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf and len(chunks) < max_chunks:
        chunks.append(buf)
    return chunks[:max_chunks]
```

- [ ] **Step 4: Run the tests**

Run: `.\dev.ps1 test tests/test_files_chunk.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/files/chunk.py tests/test_files_chunk.py
git commit -m "feat(files): chunk_text — deterministic paragraph-aware chunker"
```

---

## Task 6: `store.py` — `FileIndex` (DB store + graph)

**Files:**
- Create: `io_assistant/files/store.py`
- Test: `tests/test_files_store.py`

**Interfaces:**
- Consumes: ORM models (Task 1); `AccessGate` (Task 2); `walk_dir` /
  `FoundPath` (Task 3); a session.
- Produces:
  - `RegisterResult` dataclass: `root_id: int`, `discovered: int`,
    `skipped: list[str]`.
  - `FileIndex(session_factory)`:
    - `authorized_keys(session) -> set[str]` — `{path_key}` of every
      `registered_root` node.
    - `register(session, path: Path, gate: AccessGate, config: FilesConfig) ->
      RegisterResult` — `assert_allowed`; upsert the node
      (`registered_at=now()`, `registered_root=True`, `kind` from
      `path.is_dir()`); for a dir, upsert bare child `FileNode`s from
      `walk_dir` (path/path_key/parent_key/kind/mime/media_kind/size/mtime,
      `status="pending"`, **no content**). `RegistrationTooLarge` propagates.
    - `get(session, path_key: str) -> FileNode | None`; `by_id(session, id)`.
    - `upsert_node(session, *, path, path_key, parent_key, kind, **fields) ->
      FileNode` — insert or update-in-place, returns the row.
    - `stale(session, limit: int | None = None) -> list[FileNode]` —
      `status = 'pending' OR index_hash IS DISTINCT FROM content_hash`, ordered
      `registered_root DESC, mtime DESC NULLS LAST`.
    - `neighbors(session, file_id: int, rels: tuple[str, ...], *, limit=20) ->
      list[FileNode]` — union of: `file_edges` where `src_id=file_id AND rel IN
      rels` (→ dst) and `dst_id=file_id AND rel IN rels` (→ src); plus, if
      `"shares_entity" in rels`, other `file_id`s sharing any
      `file_entity_links (etype, entity_id)`.
    - `link_entity(session, file_id: int, etype: str, entity_id: int, *,
      source: str = "summary")` — upsert; on conflict bump `mentions`.
    - `add_edge(session, src_id: int, dst_id: int, rel: str, detail: str | None
      = None)` — upsert (no-op on conflict); never self-loop unless
      `rel == "contains"` is impossible (skip `src_id == dst_id`).
    - `forget(session, path_key: str) -> int` — delete the `registered_root`
      node whose `path_key` matches **and** every node whose `path_key` starts
      with `path_key + os.sep` (cascade clears chunks/edges/links). Returns the
      count.
    - `roots(session) -> list[FileNode]`.
    - `status_summary(session) -> dict` — `{total, indexed, stale, pending,
      errors, roots: [{path, kind, files, indexed, stale, errors}]}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_store.py
from pathlib import Path
import pytest
from tests.conftest import requires_db
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.db import models as m


def _tree(tmp_path):
    root = tmp_path / "proj"
    (root / "sub").mkdir(parents=True)
    (root / "a.md").write_text("# A\nalpha")
    (root / "sub" / "b.md").write_text("# B\nbeta")
    return root


@requires_db
def test_register_dir_creates_root_and_bare_children(db, tmp_path):
    root = _tree(tmp_path)
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    idx = FileIndex(lambda: db)
    res = idx.register(db, root, AccessGate(cfg), cfg)
    db.flush()
    assert res.discovered == 2
    rootnode = idx.get(db, AccessGate(cfg).key(root))
    assert rootnode.registered_root is True and rootnode.kind == "dir"
    kids = db.query(m.FileNode).filter(m.FileNode.kind == "file").all()
    assert {Path(k.path).name for k in kids} == {"a.md", "b.md"}
    assert all(k.status == "pending" and k.content_hash is None for k in kids)


@requires_db
def test_stale_returns_pending_and_hash_mismatch(db, tmp_path):
    root = _tree(tmp_path)
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    idx = FileIndex(lambda: db)
    idx.register(db, root, AccessGate(cfg), cfg)
    db.flush()
    node = db.query(m.FileNode).filter(m.FileNode.kind == "file").first()
    node.status = "ok"; node.content_hash = "aaa"; node.index_hash = "aaa"
    db.flush()
    assert node.id not in {n.id for n in idx.stale(db)}
    node.content_hash = "bbb"
    db.flush()
    assert node.id in {n.id for n in idx.stale(db)}


@requires_db
def test_neighbors_contains_and_shares_entity(db, tmp_path):
    idx = FileIndex(lambda: db)
    a = idx.upsert_node(db, path="/x/a.md", path_key="/x/a.md", parent_key="/x", kind="file")
    b = idx.upsert_node(db, path="/x/b.md", path_key="/x/b.md", parent_key="/x", kind="file")
    d = idx.upsert_node(db, path="/x", path_key="/x", parent_key=None, kind="dir")
    db.flush()
    idx.add_edge(db, d.id, a.id, "contains")
    idx.add_edge(db, d.id, b.id, "contains")
    idx.link_entity(db, a.id, "person", 7)
    idx.link_entity(db, b.id, "person", 7)
    db.flush()
    names = {Path(n.path).name for n in idx.neighbors(db, a.id, ("contains", "shares_entity"))}
    assert "b.md" in names          # via the shared parent OR the shared entity


@requires_db
def test_link_entity_bumps_mentions(db):
    idx = FileIndex(lambda: db)
    a = idx.upsert_node(db, path="/x/a.md", path_key="/x/a.md", parent_key="/x", kind="file")
    db.flush()
    idx.link_entity(db, a.id, "person", 3)
    idx.link_entity(db, a.id, "person", 3)
    db.flush()
    row = db.query(m.FileEntityLink).one()
    assert row.mentions == 2


@requires_db
def test_forget_cascades(db, tmp_path):
    root = _tree(tmp_path)
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    idx = FileIndex(lambda: db)
    idx.register(db, root, AccessGate(cfg), cfg)
    db.flush()
    n = idx.forget(db, AccessGate(cfg).key(root))
    db.flush()
    assert n >= 3                    # root + 2 children
    assert db.query(m.FileNode).count() == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_files_store.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `store.py`**

```python
from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, or_, select

from io_assistant.config import FilesConfig
from io_assistant.db import models as m
from io_assistant.files.paths import AccessGate
from io_assistant.files.walk import walk_dir

__all__ = ["FileIndex", "RegisterResult"]


@dataclass
class RegisterResult:
    root_id: int
    discovered: int
    skipped: list[str] = field(default_factory=list)


def _parent_key(gate: AccessGate, path: Path) -> str | None:
    parent = path.parent
    return None if parent == path else gate.key(parent)


class FileIndex:
    def __init__(self, session_factory):
        self._sf = session_factory

    # --- reads ----------------------------------------------------------
    def authorized_keys(self, session) -> set[str]:
        return set(session.execute(
            select(m.FileNode.path_key).where(m.FileNode.registered_root)
        ).scalars())

    def get(self, session, path_key: str) -> m.FileNode | None:
        return session.execute(
            select(m.FileNode).where(m.FileNode.path_key == path_key)
        ).scalar_one_or_none()

    def by_id(self, session, id: int) -> m.FileNode | None:
        return session.get(m.FileNode, id)

    def roots(self, session) -> list[m.FileNode]:
        return list(session.execute(
            select(m.FileNode).where(m.FileNode.registered_root)
            .order_by(m.FileNode.path)
        ).scalars())

    def stale(self, session, limit: int | None = None) -> list[m.FileNode]:
        stmt = (
            select(m.FileNode)
            .where(m.FileNode.kind == "file")
            .where(or_(
                m.FileNode.status == "pending",
                m.FileNode.index_hash.is_distinct_from(m.FileNode.content_hash),
            ))
            .order_by(m.FileNode.registered_root.desc(),
                      m.FileNode.mtime.desc().nullslast())
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(session.execute(stmt).scalars())

    def neighbors(self, session, file_id: int, rels: tuple[str, ...],
                  *, limit: int = 20) -> list[m.FileNode]:
        edge_rels = tuple(r for r in rels if r in ("contains", "references"))
        ids: set[int] = set()
        if edge_rels:
            ids |= set(session.execute(
                select(m.FileEdge.dst_id).where(
                    m.FileEdge.src_id == file_id, m.FileEdge.rel.in_(edge_rels))
            ).scalars())
            ids |= set(session.execute(
                select(m.FileEdge.src_id).where(
                    m.FileEdge.dst_id == file_id, m.FileEdge.rel.in_(edge_rels))
            ).scalars())
        if "shares_entity" in rels:
            mine = select(m.FileEntityLink.etype, m.FileEntityLink.entity_id).where(
                m.FileEntityLink.file_id == file_id).subquery()
            ids |= set(session.execute(
                select(m.FileEntityLink.file_id)
                .join(mine, (m.FileEntityLink.etype == mine.c.etype)
                      & (m.FileEntityLink.entity_id == mine.c.entity_id))
                .where(m.FileEntityLink.file_id != file_id)
            ).scalars())
        ids.discard(file_id)
        if not ids:
            return []
        return list(session.execute(
            select(m.FileNode).where(m.FileNode.id.in_(list(ids)[:limit]))
        ).scalars())

    # --- writes --------------------------------------------------------
    def upsert_node(self, session, *, path: str, path_key: str,
                    parent_key: str | None, kind: str, **fields) -> m.FileNode:
        node = self.get(session, path_key)
        if node is None:
            node = m.FileNode(path=path, path_key=path_key,
                              parent_key=parent_key, kind=kind, **fields)
            session.add(node)
            session.flush()
            return node
        node.path = path
        node.parent_key = parent_key
        node.kind = kind
        for k, v in fields.items():
            setattr(node, k, v)
        session.flush()
        return node

    def register(self, session, path: Path, gate: AccessGate,
                 config: FilesConfig) -> RegisterResult:
        keys = self.authorized_keys(session)
        gate.assert_allowed(path, registered_keys=keys)
        is_dir = path.is_dir()
        root = self.upsert_node(
            session, path=str(path), path_key=gate.key(path),
            parent_key=_parent_key(gate, path),
            kind="dir" if is_dir else "file",
            registered_at=dt.datetime.now(dt.timezone.utc),
            registered_root=True,
        )
        discovered = 0
        skipped: list[str] = []
        if is_dir:
            for fp in walk_dir(path, config, gate):
                self.upsert_node(
                    session, path=str(fp.path), path_key=gate.key(fp.path),
                    parent_key=gate.key(fp.path.parent), kind="file",
                    mime=fp.mime, media_kind=fp.media_kind,
                    size_bytes=fp.size, mtime=fp.mtime, status="pending",
                )
                discovered += 1
        return RegisterResult(root_id=root.id, discovered=discovered, skipped=skipped)

    def link_entity(self, session, file_id: int, etype: str, entity_id: int,
                    *, source: str = "summary") -> None:
        row = session.execute(
            select(m.FileEntityLink).where(
                m.FileEntityLink.file_id == file_id,
                m.FileEntityLink.etype == etype,
                m.FileEntityLink.entity_id == entity_id)
        ).scalar_one_or_none()
        if row is None:
            session.add(m.FileEntityLink(file_id=file_id, etype=etype,
                                         entity_id=entity_id, source=source))
        else:
            row.mentions += 1
        session.flush()

    def add_edge(self, session, src_id: int, dst_id: int, rel: str,
                 detail: str | None = None) -> None:
        if src_id == dst_id:
            return
        exists = session.execute(
            select(m.FileEdge.id).where(
                m.FileEdge.src_id == src_id, m.FileEdge.dst_id == dst_id,
                m.FileEdge.rel == rel)
        ).scalar_one_or_none()
        if exists is None:
            session.add(m.FileEdge(src_id=src_id, dst_id=dst_id, rel=rel, detail=detail))
            session.flush()

    def forget(self, session, path_key: str) -> int:
        prefix = path_key.rstrip(os.sep) + os.sep
        rows = list(session.execute(
            select(m.FileNode).where(or_(
                m.FileNode.path_key == path_key,
                m.FileNode.path_key.startswith(prefix)))
        ).scalars())
        for r in rows:
            session.delete(r)
        session.flush()
        return len(rows)

    def status_summary(self, session) -> dict:
        total = session.execute(
            select(func.count()).select_from(m.FileNode)
            .where(m.FileNode.kind == "file")).scalar_one()
        indexed = session.execute(
            select(func.count()).select_from(m.FileNode)
            .where(m.FileNode.status == "ok")).scalar_one()
        errors = session.execute(
            select(func.count()).select_from(m.FileNode)
            .where(m.FileNode.status.in_(("unreadable", "too_large", "missing")))
        ).scalar_one()
        pending = session.execute(
            select(func.count()).select_from(m.FileNode)
            .where(m.FileNode.status == "pending")).scalar_one()
        stale = len(self.stale(session))
        return {
            "total": total, "indexed": indexed, "stale": stale,
            "pending": pending, "errors": errors,
            "roots": [
                {"path": r.path, "kind": r.kind}
                for r in self.roots(session)
            ],
        }
```

*Note:* `is_distinct_from` — on SQLAlchemy 2.x it is
`Column.is_distinct_from(other)`; if the installed version lacks it use
`sa.text` / `or_(a.is_(None) != b.is_(None), a != b)`. Verify at implementation
time.

- [ ] **Step 4: Run the tests**

Run: `.\dev.ps1 test tests/test_files_store.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/files/store.py tests/test_files_store.py
git commit -m "feat(files): FileIndex — register, staleness, graph traversal, forget"
```

---

## Task 7: `Backend.summarize_file` + `answer_from_files`

**Files:**
- Modify: `io_assistant/backend/interface.py` (Protocol)
- Modify: `io_assistant/backend/local.py`, `anthropic_backend.py`, `hybrid.py`
- Create: `io_assistant/prompts/file_summary.txt`, `file_answer.txt`
- Modify: `tests/conftest.py` (`FakeBackend`)
- Test: `tests/test_backend_files.py`

**Interfaces:**
- Consumes: `render_context`, `BackendParseError` (existing).
- Produces (on every `Backend`):
  - `summarize_file(title: str, head_text: str, *, mime: str | None = None) ->
    dict` — returns `{"summary": str, "names": list[str], "references":
    list[str]}`. Raises `BackendParseError` if the model output is not a JSON
    object with those keys (coerce missing lists to `[]`, missing summary to
    `""`).
  - `answer_from_files(question: str, files: list[dict], shape: str, *,
    context: str | None = None) -> str` — `files` entries are
    `{"path","title","summary","excerpts": list[str]}`.
  - `FakeBackend.set_file_summary(dict)`, `.set_file_answer(str)`,
    `.last_files` (the `files` arg of the last `answer_from_files` call),
    `.last_summarize` (the `(title, head_text)` of the last call). Both methods
    append to `.calls`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backend_files.py
import httpx
import pytest
from io_assistant.backend.local import LocalBackend
from io_assistant.backend.interface import Backend, BackendParseError


def _patch_chat(monkeypatch, content):
    class R:
        def raise_for_status(self): ...
        def json(self): return {"message": {"content": content}}
    class C:
        def __init__(self, *a, **k): ...
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, json): C.last = json; return R()
    monkeypatch.setattr(httpx, "Client", C)
    return C


def test_fakebackend_still_satisfies_protocol(fake_backend):
    assert isinstance(fake_backend, Backend)


def test_summarize_file_parses(config, monkeypatch):
    _patch_chat(monkeypatch, '{"summary":"A lease.","names":["Mr Khan"],"references":["bill.pdf"]}')
    out = LocalBackend(config).summarize_file("Lease", "the lease text")
    assert out["summary"] == "A lease."
    assert out["names"] == ["Mr Khan"]
    assert out["references"] == ["bill.pdf"]


def test_summarize_file_bad_json_raises(config, monkeypatch):
    _patch_chat(monkeypatch, "not json")
    with pytest.raises(BackendParseError):
        LocalBackend(config).summarize_file("x", "y")


def test_answer_from_files_calls_model(config, monkeypatch):
    _patch_chat(monkeypatch, "Your lease allows pets with a deposit.")
    ans = LocalBackend(config).answer_from_files(
        "pets?", [{"path": "/x/lease.md", "title": "Lease",
                   "summary": "s", "excerpts": ["Pets are allowed with a deposit."]}],
        "text")
    assert "pets" in ans.lower()


def test_fake_setters(fake_backend):
    fake_backend.set_file_summary({"summary": "s", "names": ["Nafay"], "references": []})
    fake_backend.set_file_answer("done")
    assert fake_backend.summarize_file("t", "h")["names"] == ["Nafay"]
    assert fake_backend.answer_from_files("q", [{"path": "/a"}], "text") == "done"
    assert fake_backend.last_files == [{"path": "/a"}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_backend_files.py -q`
Expected: FAIL — `AttributeError: 'LocalBackend' object has no attribute 'summarize_file'`.

- [ ] **Step 3: Add the prompts**

`io_assistant/prompts/file_summary.txt`:
```
Summarise ONE file for a personal search index. Output ONE JSON object, nothing else:

{"summary": "<=3 sentences, plain, what this file is and contains>",
 "names": ["proper names of people, organisations, or places named in the file"],
 "references": ["names or paths of OTHER files this file points to, verbatim"]}

Rules: summary <= 400 characters. names: only real proper nouns, no dates, no
common words. references: only if the text actually cites another file. If a
list is empty, use []. Do not invent.

Title: {title}
MIME: {mime}
--- file text (may be truncated) ---
{head}
--- end ---
JSON:
```

`io_assistant/prompts/file_answer.txt`:
```
Answer the user's question using ONLY the file material below. Cite the file
path(s) you used, in parentheses. If the material does not contain the answer,
say so plainly and do not guess. Match the requested shape ({shape}: text or
markdown).

{context}Question:
{question}

Files:
{files}

Answer:
```

- [ ] **Step 4: Implement in `local.py`**

```python
def summarize_file(self, title: str, head_text: str, *, mime: str | None = None) -> dict:
    out = self._chat(
        "You summarise a file into one JSON object. Output JSON only.",
        _load_prompt("file_summary.txt").format(
            title=title or "(untitled)", mime=mime or "unknown",
            head=head_text[:6000],
        ),
        json_mode=True,
    )
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, TypeError) as e:
        raise BackendParseError(str(e)) from e
    if not isinstance(data, dict):
        raise BackendParseError(f"summary is not an object: {out!r}")
    return {
        "summary": str(data.get("summary") or "")[:400],
        "names": [str(x) for x in (data.get("names") or []) if str(x).strip()],
        "references": [str(x) for x in (data.get("references") or []) if str(x).strip()],
    }

def answer_from_files(self, question: str, files: list[dict], shape: str,
                      *, context: str | None = None) -> str:
    blocks = []
    for f in files:
        ex = "\n".join(f"  - {e}" for e in f.get("excerpts", []))
        blocks.append(
            f"[{f.get('path')}] {f.get('title') or ''}\n"
            f"  summary: {f.get('summary') or ''}\n{ex}"
        )
    return self._chat(
        "You answer strictly from the provided files.",
        _load_prompt("file_answer.txt").format(
            context=render_context(context), question=question,
            files="\n\n".join(blocks), shape=shape,
        ),
        json_mode=False,
    ).strip()
```

- [ ] **Step 5: Implement in `anthropic_backend.py`**

Same bodies, using `self._complete(system, user, max_tokens=...)`:
`summarize_file` → `max_tokens=300`; `answer_from_files` → `max_tokens=500`.
Parse `summarize_file` output with `json.loads` (Claude may wrap in text — strip
to the first `{` … last `}` before parsing, mirroring the existing `extract`
handling in that file).

- [ ] **Step 6: Implement in `hybrid.py`**

```python
def summarize_file(self, title, head_text, *, mime=None):
    return self._local.summarize_file(title, head_text, mime=mime)

def answer_from_files(self, question, files, shape, *, context=None):
    return self._cloud.answer_from_files(question, files, shape, context=context)
```

- [ ] **Step 7: Add to the `Backend` Protocol in `interface.py`**

```python
def summarize_file(self, title: str, head_text: str, *,
                   mime: str | None = None) -> dict: ...

def answer_from_files(self, question: str, files: list[dict], shape: str,
                      *, context: str | None = None) -> str: ...
```

- [ ] **Step 8: Extend `FakeBackend` in `conftest.py`**

```python
# __init__: self._file_summary = {"summary": "", "names": [], "references": []}
#           self._file_answer = ""
#           self.last_files = None
#           self.last_summarize = None
def set_file_summary(self, d): self._file_summary = d
def set_file_answer(self, s): self._file_answer = s
def summarize_file(self, title, head_text, *, mime=None):
    self.calls.append("summarize_file"); self.last_summarize = (title, head_text)
    return self._file_summary
def answer_from_files(self, question, files, shape, *, context=None):
    self._ctx(context); self.calls.append("answer_from_files"); self.last_files = files
    return self._file_answer
```

- [ ] **Step 9: Run the tests**

Run: `.\dev.ps1 test tests/test_backend_files.py tests/test_backend_interface.py tests/test_backend_local.py tests/test_backend_anthropic.py -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add io_assistant/backend/ io_assistant/prompts/file_summary.txt \
  io_assistant/prompts/file_answer.txt tests/conftest.py tests/test_backend_files.py
git commit -m "feat(files): Backend.summarize_file + answer_from_files (+ prompts, fakes)"
```

---

## Task 8: `index.py` — `FileIndexer` (index one path)

**Files:**
- Create: `io_assistant/files/index.py`
- Test: `tests/test_files_index.py`

**Interfaces:**
- Consumes: `Embedder`/`StubEmbedder`; `Backend`/`FakeBackend`; `FilesConfig`;
  `AccessGate`; `read_document` (Task 4); `chunk_text` (Task 5); `FileIndex`
  (Task 6); `resolve_query_entities` (`io_assistant/query/entities.py`);
  `EntityResolver`.
- Produces:
  - `FileIndexer(embedder, backend, config, resolver_cfg)` where `resolver_cfg`
    is `config.resolver` (a `ResolverConfig`).
  - `index_path(session, path: Path, *, gate: AccessGate, force: bool = False)
    -> FileNode` — the full pipeline from spec §5.5. Returns the updated node.
  - `build_reference_edges(session, node, references: list[str], index:
    FileIndex)` — helper (also unit-tested).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_index.py
import datetime as dt
from pathlib import Path
import pytest
from tests.conftest import requires_db, StubEmbedder
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.index import FileIndexer
from io_assistant.db import models as m


def _indexer(config, fake_backend):
    return FileIndexer(StubEmbedder(), fake_backend, FilesConfig(), config.resolver)


@requires_db
def test_index_text_file_writes_chunks_and_summary(db, config, fake_backend, tmp_path):
    f = tmp_path / "lease.md"
    f.write_text("# Lease\n\n" + "Pets are allowed with a deposit. " * 40)
    fake_backend.set_file_summary({"summary": "A lease about pets.", "names": [], "references": []})
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    node = _indexer(config, fake_backend).index_path(db, f, gate=gate)
    db.flush()
    assert node.status == "ok"
    assert node.summary == "A lease about pets."
    assert node.index_hash == node.content_hash
    assert db.query(m.FileChunk).filter_by(file_id=node.id).count() >= 1


@requires_db
def test_reindex_same_hash_is_noop(db, config, fake_backend, tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# A\nalpha beta")
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    idxr = _indexer(config, fake_backend)
    idxr.index_path(db, f, gate=gate); db.flush()
    fake_backend.calls.clear()
    idxr.index_path(db, f, gate=gate); db.flush()
    assert "summarize_file" not in fake_backend.calls


@requires_db
def test_entities_linked_only_on_resolver_hit(db, config, fake_backend, tmp_path):
    db.add(m.Person(canonical_name="Nafay", aliases=[]))
    db.flush()
    f = tmp_path / "trip.md"
    f.write_text("# Trip\nWe went with Nafay and someone else.")
    fake_backend.set_file_summary({"summary": "trip", "names": ["Nafay", "Zzxq"], "references": []})
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    node = _indexer(config, fake_backend).index_path(db, f, gate=gate)
    db.flush()
    links = db.query(m.FileEntityLink).filter_by(file_id=node.id).all()
    assert [(l.etype, l.entity_id) for l in links] == [("person", db.query(m.Person).one().id)]


@requires_db
def test_reference_string_creates_edge(db, config, fake_backend, tmp_path):
    (tmp_path / "bill.pdf").write_bytes(b"%PDF-1.4 fake")
    other = tmp_path / "notes.md"
    other.write_text("# Notes\nsee bill.pdf")
    idx = FileIndex(lambda: db)
    idx.upsert_node(db, path=str(tmp_path / "bill.pdf"),
                    path_key=str(tmp_path / "bill.pdf").lower(),
                    parent_key=str(tmp_path).lower(), kind="file")
    db.flush()
    fake_backend.set_file_summary({"summary": "n", "names": [], "references": ["bill.pdf"]})
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    node = _indexer(config, fake_backend).index_path(db, other, gate=gate)
    db.flush()
    assert db.query(m.FileEdge).filter_by(src_id=node.id, rel="references").count() == 1


@requires_db
def test_summary_parse_error_falls_back(db, config, fake_backend, tmp_path):
    from io_assistant.backend.interface import BackendParseError

    class Boom(type(fake_backend)):
        def summarize_file(self, *a, **k): raise BackendParseError("bad")

    b = Boom()
    f = tmp_path / "x.md"
    f.write_text("# X\nsome content here")
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    node = FileIndexer(StubEmbedder(), b, FilesConfig(), config.resolver).index_path(db, f, gate=gate)
    db.flush()
    assert node.status == "ok" and node.summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_files_index.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `index.py`**

```python
from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path

from sqlalchemy import select

from io_assistant.backend.interface import BackendParseError
from io_assistant.config import FilesConfig, ResolverConfig
from io_assistant.db import models as m
from io_assistant.files.chunk import chunk_text
from io_assistant.files.extract import read_document
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.walk import classify_media
from io_assistant.query.entities import resolve_query_entities
from io_assistant.resolve.resolver import EntityResolver

__all__ = ["FileIndexer"]


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class FileIndexer:
    def __init__(self, embedder, backend, config: FilesConfig,
                 resolver_cfg: ResolverConfig):
        self._embed = embedder
        self._backend = backend
        self._cfg = config
        self._resolver_cfg = resolver_cfg
        self._index = FileIndex(lambda: None)

    def index_path(self, session, path: Path, *, gate: AccessGate,
                   force: bool = False) -> m.FileNode:
        pk = gate.key(path)
        parent_key = gate.key(path.parent) if path.parent != path else None

        if not path.exists():
            return self._index.upsert_node(
                session, path=str(path), path_key=pk, parent_key=parent_key,
                kind="file", status="missing", error="file not found")

        st = path.stat()
        content_hash = _hash(path)
        node = self._index.get(session, pk)
        if (not force and node is not None and node.status == "ok"
                and node.index_hash == content_hash):
            return node

        media_kind = classify_media(path.suffix, self._cfg)
        node = self._index.upsert_node(
            session, path=str(path), path_key=pk, parent_key=parent_key,
            kind="file", mime=node.mime if node else None,
            media_kind=media_kind, size_bytes=st.st_size,
            content_hash=content_hash,
            mtime=dt.datetime.fromtimestamp(st.st_mtime, tz=dt.timezone.utc),
        )

        if media_kind is not None:
            # media: metadata only here; Spec C handles captions/thumbs
            node.status = "ok"
            node.index_hash = content_hash
            node.indexed_at = dt.datetime.now(dt.timezone.utc)
            session.flush()
            self._contains_edge(session, node, gate)
            return node

        doc = read_document(path, self._cfg)
        if doc.status != "ok":
            node.status = doc.status
            node.error = doc.error
            node.title = doc.title or path.stem
            node.index_hash = content_hash
            node.indexed_at = dt.datetime.now(dt.timezone.utc)
            session.flush()
            return node

        # chunks + embeddings (always local)
        session.query(m.FileChunk).filter_by(file_id=node.id).delete()
        chunks = chunk_text(
            doc.text, chunk_tokens=self._cfg.chunk_tokens,
            overlap=self._cfg.chunk_overlap, max_chunks=self._cfg.max_chunks_per_file)
        if chunks:
            vecs = self._embed.embed(chunks)
            for i, (c, v) in enumerate(zip(chunks, vecs)):
                session.add(m.FileChunk(file_id=node.id, ord=i, text=c,
                                        token_estimate=len(c) // 4, embedding=v))

        # summary + entities + references
        try:
            res = self._backend.summarize_file(doc.title, doc.text, mime=node.mime)
        except BackendParseError:
            res = {"summary": doc.text[:200], "names": [], "references": []}
        summary = (res.get("summary") or doc.text[:200])[:400]
        node.summary = summary
        node.title = doc.title or path.stem
        node.embedding = self._embed.embed_one(summary)

        resolver = EntityResolver(session, self._embed, self._resolver_cfg)
        by_type = resolve_query_entities(resolver, session, res.get("names", []))
        for etype, ids in by_type.items():
            for eid in ids:
                self._index.link_entity(session, node.id, etype, eid, source="summary")

        self._reference_edges(session, node, res.get("references", []))
        self._contains_edge(session, node, gate)

        node.status = "ok"
        node.index_hash = content_hash
        node.indexed_at = dt.datetime.now(dt.timezone.utc)
        session.flush()
        return node

    def _contains_edge(self, session, node: m.FileNode, gate: AccessGate) -> None:
        if node.parent_key is None:
            return
        parent = self._index.get(session, node.parent_key)
        if parent is None:
            parent = self._index.upsert_node(
                session, path=str(Path(node.path).parent),
                path_key=node.parent_key,
                parent_key=gate.key(Path(node.path).parent.parent),
                kind="dir")
        self._index.add_edge(session, parent.id, node.id, "contains")

    def _reference_edges(self, session, node: m.FileNode, refs: list[str]) -> None:
        for raw in refs:
            s = raw.strip().replace("\\", "/").lower()
            base = s.rsplit("/", 1)[-1]
            if not base:
                continue
            hit = session.execute(
                select(m.FileNode).where(m.FileNode.id != node.id).where(
                    m.FileNode.path_key.endswith(s)
                    | m.FileNode.path_key.endswith("/" + base)
                    | (m.FileNode.path_key == base))
            ).scalars().first()
            if hit is not None:
                self._index.add_edge(session, node.id, hit.id, "references", detail=raw)
```

- [ ] **Step 4: Run the tests**

Run: `.\dev.ps1 test tests/test_files_index.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/files/index.py tests/test_files_index.py
git commit -m "feat(files): FileIndexer — hash-gated read/chunk/embed/summarise/link"
```

---

## Task 9: `command.py` — register-vs-search classification

**Files:**
- Create: `io_assistant/files/command.py`
- Test: `tests/test_files_command.py`

**Interfaces:**
- Consumes: `FilesConfig`, `AccessGate`, a session, ORM `FileNode`.
- Produces:
  - `FileCommand` dataclass: `action: Literal["register", "search"]`,
    `path: str | None`, `phrase: str | None`.
  - `classify_file_command(text: str) -> FileCommand`.
  - `ResolveResult` dataclass: `kind: Literal["one","many","none"]`,
    `path: Path | None`, `candidates: list[Path]`.
  - `resolve_register_target(phrase: str, session, gate: AccessGate,
    config: FilesConfig) -> ResolveResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_command.py
from pathlib import Path
import pytest
from tests.conftest import requires_db
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.command import classify_file_command, resolve_register_target


@pytest.mark.parametrize("text,action", [
    ("remember my Taxes folder in Documents", "register"),
    ("index C:\\Users\\me\\resume.pdf", "register"),
    ("keep track of the notes in ~/work", "register"),
    ("what does my lease say about pets", "search"),
    ("find the Granjur invoice", "search"),
    ("show me the files about Nafay", "search"),
])
def test_action_classification(text, action):
    assert classify_file_command(text).action == action


def test_explicit_windows_path_extracted():
    c = classify_file_command("index C:\\Users\\me\\resume.pdf")
    assert c.path == "C:\\Users\\me\\resume.pdf"


def test_phrase_when_no_explicit_path():
    c = classify_file_command("remember my Taxes folder in Documents")
    assert c.path is None and "Taxes" in c.phrase


@requires_db
def test_resolve_matches_registered_dir(db, tmp_path):
    d = tmp_path / "Taxes 2025"
    d.mkdir()
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    gate = AccessGate(cfg)
    FileIndex(lambda: db).register(db, d, gate, cfg)
    db.flush()
    r = resolve_register_target("taxes 2025", db, gate, cfg)
    assert r.kind == "one" and r.path == d


@requires_db
def test_resolve_ambiguous(db, tmp_path):
    for name in ("Trip Photos", "Trip Notes"):
        (tmp_path / name).mkdir()
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    r = resolve_register_target("trip", db, AccessGate(cfg), cfg)
    assert r.kind == "many" and len(r.candidates) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_files_command.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `command.py`**

```python
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz
from sqlalchemy import select

from io_assistant.config import FilesConfig
from io_assistant.db import models as m
from io_assistant.files.paths import AccessGate

__all__ = [
    "FileCommand", "classify_file_command",
    "ResolveResult", "resolve_register_target",
]

_PATH_RE = re.compile(r"([A-Za-z]:\\[^\"\n]+|/[^\"\n]+|~[/\\][^\"\n]+)")
_REGISTER_RE = re.compile(
    r"\b(remember|index|register|watch|keep track of|add\s+(?:the\s+)?[\w .\-/]+\s+to\s+(?:your|my)\s+files)\b",
    re.I,
)
_AFTER_VERB_RE = re.compile(
    r"\b(?:remember|index|register|watch|keep track of)\b\s+(.*)", re.I)
_STOPWORDS = {"the", "my", "a", "folder", "directory", "called", "named",
              "in", "under", "at", "of", "files", "file"}


@dataclass
class FileCommand:
    action: Literal["register", "search"]
    path: str | None = None
    phrase: str | None = None


def classify_file_command(text: str) -> FileCommand:
    t = text.strip()
    path_m = _PATH_RE.search(t)
    path = path_m.group(1).strip().rstrip(".") if path_m else None
    if _REGISTER_RE.search(t):
        phrase = None
        if path is None:
            am = _AFTER_VERB_RE.search(t)
            if am:
                phrase = am.group(1).strip().rstrip(".?!")
        return FileCommand("register", path=path, phrase=phrase)
    return FileCommand("search", path=path)


@dataclass
class ResolveResult:
    kind: Literal["one", "many", "none"]
    path: Path | None = None
    candidates: list[Path] = field(default_factory=list)


def _keywords(phrase: str) -> list[str]:
    return [w for w in re.split(r"[\s/\\]+", phrase.lower()) if w and w not in _STOPWORDS]


def _candidate_dirs(session, gate: AccessGate, config: FilesConfig) -> list[Path]:
    out: list[Path] = []
    for pk in session.execute(
        select(m.FileNode.path).where(m.FileNode.kind == "dir")
    ).scalars():
        out.append(Path(pk))
    for root in gate.roots:
        try:
            for child in os.scandir(root):
                if child.is_dir(follow_symlinks=config.follow_symlinks) \
                        and not gate.is_excluded(Path(child.path)):
                    out.append(Path(child.path))
        except OSError:
            continue
    # dedupe by key
    seen: dict[str, Path] = {}
    for p in out:
        seen.setdefault(gate.key(p), p)
    return list(seen.values())


def resolve_register_target(phrase: str, session, gate: AccessGate,
                            config: FilesConfig) -> ResolveResult:
    kws = _keywords(phrase or "")
    if not kws:
        return ResolveResult("none")
    scored: list[tuple[float, Path]] = []
    for d in _candidate_dirs(session, gate, config):
        name = d.name.lower()
        score = fuzz.token_set_ratio(" ".join(kws), name)
        if all(k in name for k in kws):
            score = max(score, 95)
        if score >= 80:
            scored.append((score, d))
    scored.sort(key=lambda s: s[0], reverse=True)
    if not scored:
        return ResolveResult("none")
    if len(scored) == 1 or scored[0][0] - scored[1][0] >= 15:
        return ResolveResult("one", path=scored[0][1])
    return ResolveResult("many", candidates=[p for _, p in scored[:5]])
```

- [ ] **Step 4: Run the tests**

Run: `.\dev.ps1 test tests/test_files_command.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/files/command.py tests/test_files_command.py
git commit -m "feat(files): classify_file_command + fuzzy register-target resolution"
```

---

## Task 10: `search.py` + `cards.py` — deterministic file search

**Files:**
- Create: `io_assistant/files/search.py`, `io_assistant/files/cards.py`
- Test: `tests/test_files_search.py`

**Interfaces:**
- Consumes: `Embedder`/`StubEmbedder`; `Backend`/`FakeBackend`; `FilesConfig`;
  `AccessGate`; `FileIndex` (Task 6); `FileIndexer` (Task 8); `EntityResolver`
  + `resolve_query_entities`; `models_domain.FileHit`, `FilesCard`.
- Produces:
  - `FileAnswer` dataclass: `text: str`, `shape: str`, `hits: list[FileHit]`,
    `searched: int`.
  - `FileSearcher(embedder, backend, config, resolver_cfg)`:
    - `.search(session, question: str, now, *, gate: AccessGate,
      context: str | None = None) -> FileAnswer`.
  - `cards.files_card(answer: FileAnswer) -> FilesCard`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_search.py
import datetime as dt
from pathlib import Path
import pytest
from tests.conftest import requires_db, StubEmbedder
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.search import FileSearcher
from io_assistant.files.cards import files_card
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)


def _seed_file(db, tmp_path, name, body, hero="hero"):
    p = tmp_path / name
    p.write_text(body)
    idx = FileIndex(lambda: db)
    node = idx.upsert_node(db, path=str(p), path_key=str(p).lower(),
                           parent_key=str(tmp_path).lower(), kind="file",
                           status="ok", content_hash="h", index_hash="h",
                           title=name, summary=body[:100],
                           mtime=NOW, embedding=[0.0] * 768)
    db.add(m.FileChunk(file_id=node.id, ord=0, text=body,
                       token_estimate=len(body) // 4,
                       embedding=StubEmbedder({hero: [1.0] + [0.0] * 767}).embed_one(hero)))
    db.flush()
    return node


def _searcher(config, fake_backend):
    return FileSearcher(StubEmbedder({"pets": [1.0] + [0.0] * 767}),
                        fake_backend, FilesConfig(), config.resolver)


@requires_db
def test_search_finds_by_fulltext(db, config, fake_backend, tmp_path):
    _seed_file(db, tmp_path, "lease.md", "Pets are allowed with a deposit here.", hero="pets")
    fake_backend.set_file_answer("Pets are allowed with a deposit. (lease.md)")
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    ans = _searcher(config, fake_backend).search(db, "what about pets", NOW, gate=gate)
    assert "deposit" in ans.text
    assert ans.hits and ans.hits[0].path.endswith("lease.md")


@requires_db
def test_empty_result_is_deterministic_no_model(db, config, fake_backend, tmp_path):
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    ans = _searcher(config, fake_backend).search(db, "nothing here", NOW, gate=gate)
    assert "answer_from_files" not in fake_backend.calls
    assert ans.hits == []


@requires_db
def test_freshness_reindexes_changed_file(db, config, fake_backend, tmp_path):
    node = _seed_file(db, tmp_path, "n.md", "old content about pets", hero="pets")
    (tmp_path / "n.md").write_text("new content about pets and deposits")
    node.content_hash = "STALE"        # force mismatch vs on-disk
    db.flush()
    fake_backend.set_file_summary({"summary": "s", "names": [], "references": []})
    fake_backend.set_file_answer("ok (n.md)")
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    _searcher(config, fake_backend).search(db, "pets", NOW, gate=gate)
    db.refresh(node)
    assert node.index_hash == node.content_hash != "STALE"


@requires_db
def test_retrieval_limit_enforced(db, config, fake_backend, tmp_path):
    for i in range(10):
        _seed_file(db, tmp_path, f"f{i}.md", "pets pets pets deposit", hero="pets")
    fake_backend.set_file_answer("many (f0.md)")
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)], retrieval_file_limit=3)
    s = FileSearcher(StubEmbedder({"pets": [1.0] + [0.0] * 767}), fake_backend, cfg, config.resolver)
    ans = s.search(db, "pets", NOW, gate=AccessGate(cfg))
    assert len(ans.hits) <= 3
    assert len(fake_backend.last_files) <= 3


def test_files_card_builder():
    from io_assistant.files.search import FileAnswer
    from io_assistant.models_domain import FileHit
    c = files_card(FileAnswer("t", "text", [FileHit(path="/x/a.md", title="A", why="w")], 5))
    assert c.type == "files" and c.searched == 5 and c.hits[0].path == "/x/a.md"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_files_search.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `cards.py`**

```python
from __future__ import annotations

from io_assistant.models_domain import FilesCard

__all__ = ["files_card"]


def files_card(answer) -> FilesCard:
    return FilesCard(hits=list(answer.hits), searched=answer.searched)
```

- [ ] **Step 4: Implement `search.py`**

```python
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select, text as sqltext

from io_assistant.config import FilesConfig, ResolverConfig
from io_assistant.db import models as m
from io_assistant.files.index import FileIndexer
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.models_domain import FileHit
from io_assistant.query.entities import resolve_query_entities
from io_assistant.resolve.resolver import EntityResolver

__all__ = ["FileSearcher", "FileAnswer"]

_RELS = ("contains", "references", "shares_entity")


@dataclass
class FileAnswer:
    text: str
    shape: str
    hits: list[FileHit] = field(default_factory=list)
    searched: int = 0


@dataclass
class _Cand:
    file_id: int
    lexical: float = 0.0
    similarity: float = 0.0
    entity: float = 0.0
    neighbor: float = 0.0
    why: str = ""


class FileSearcher:
    def __init__(self, embedder, backend, config: FilesConfig,
                 resolver_cfg: ResolverConfig):
        self._embed = embedder
        self._backend = backend
        self._cfg = config
        self._resolver_cfg = resolver_cfg
        self._index = FileIndex(lambda: None)
        self._indexer = FileIndexer(embedder, backend, config, resolver_cfg)

    def search(self, session, question: str, now, *, gate: AccessGate,
               context: str | None = None) -> FileAnswer:
        cands: dict[int, _Cand] = {}

        def bump(fid, **kw):
            c = cands.setdefault(fid, _Cand(file_id=fid))
            for k, v in kw.items():
                if k == "why" and v and not c.why:
                    c.why = v
                elif k != "why":
                    setattr(c, k, max(getattr(c, k), v))

        # 1a lexical: FTS on chunks
        rows = session.execute(
            select(m.FileChunk.file_id,
                   func.ts_rank(m.FileChunk.tsv,
                                func.plainto_tsquery("english", question)).label("r"))
            .where(m.FileChunk.tsv.op("@@")(func.plainto_tsquery("english", question)))
            .order_by(sqltext("r DESC")).limit(30)
        ).all()
        for fid, r in rows:
            bump(fid, lexical=float(r), why=f'matches "{question[:40]}"')

        # 1a lexical: ILIKE on node title/path/summary
        like = f"%{question.strip()[:60]}%"
        for fid in session.execute(
            select(m.FileNode.id).where(m.FileNode.kind == "file").where(
                m.FileNode.title.ilike(like) | m.FileNode.path.ilike(like)
                | m.FileNode.summary.ilike(like)).limit(15)
        ).scalars():
            bump(fid, lexical=0.5, why="name/summary match")

        # 1b semantic
        qvec = self._embed.embed_one(question)
        for fid, dist in session.execute(
            select(m.FileChunk.file_id,
                   m.FileChunk.embedding.cosine_distance(qvec).label("d"))
            .order_by(sqltext("d ASC")).limit(30)
        ).all():
            bump(fid, similarity=1.0 - float(dist), why="similar content")
        for fid, dist in session.execute(
            select(m.FileNode.id,
                   m.FileNode.embedding.cosine_distance(qvec).label("d"))
            .where(m.FileNode.embedding.isnot(None))
            .order_by(sqltext("d ASC")).limit(15)
        ).all():
            bump(fid, similarity=1.0 - float(dist), why="similar summary")

        # 1c entity
        resolver = EntityResolver(session, self._embed, self._resolver_cfg)
        names = [w for w in question.split() if w[:1].isupper()]
        if names:
            by_type = resolve_query_entities(resolver, session, names)
            ent_ids = [(et, i) for et, ids in by_type.items() for i in ids]
            for et, eid in ent_ids:
                for fid, ename in session.execute(
                    select(m.FileEntityLink.file_id, _entity_name(et))
                    .join(_entity_model(et), _entity_model(et).id == m.FileEntityLink.entity_id)
                    .where(m.FileEntityLink.etype == et, m.FileEntityLink.entity_id == eid)
                ).all():
                    bump(fid, entity=1.0, why=f"mentions {ename}")

        # 1d graph expansion (one hop)
        for fid in list(cands):
            for nb in self._index.neighbors(session, fid, _RELS, limit=8):
                bump(nb.id, neighbor=0.3, why="linked to a match")

        searched = len(cands)
        if not cands:
            return FileAnswer("I don't have any files that cover that yet.",
                              "text", [], 0)

        # 2 rank
        nodes = {n.id: n for n in session.execute(
            select(m.FileNode).where(m.FileNode.id.in_(list(cands)))
        ).scalars()}
        scored = []
        for c in cands.values():
            n = nodes.get(c.file_id)
            if n is None or n.kind != "file":
                continue
            age_days = max(0.0, (now - n.mtime).total_seconds() / 86400) if n.mtime else 365
            recency = math.exp(-age_days / 45)
            score = (0.30 * recency + 0.30 * c.similarity + 0.20 * min(c.lexical, 1.0)
                     + 0.15 * c.entity + 0.05 * c.neighbor)
            scored.append((score, c, n))
        scored.sort(key=lambda s: s[0], reverse=True)
        kept = scored[: self._cfg.retrieval_file_limit]

        # 3 freshness
        final: list[tuple[_Cand, m.FileNode]] = []
        for _, c, n in kept:
            p = Path(n.path)
            if not p.exists():
                n.status = "missing"
                session.flush()
                continue
            self._indexer.index_path(session, p, gate=gate, force=False)
            session.refresh(n)
            final.append((c, n))
        if not final:
            return FileAnswer("I don't have any files that cover that yet.",
                              "text", [], searched)

        # 4 answer
        payload = []
        hits: list[FileHit] = []
        for c, n in final:
            excerpts = list(session.execute(
                select(m.FileChunk.text).where(m.FileChunk.file_id == n.id)
                .order_by(m.FileChunk.ord).limit(3)
            ).scalars())
            payload.append({"path": n.path, "title": n.title,
                            "summary": n.summary or "", "excerpts": excerpts})
            hits.append(FileHit(path=n.path, title=n.title, why=c.why or "match",
                                media_kind=n.media_kind))
        answer = self._backend.answer_from_files(question, payload, "text",
                                                 context=context)
        return FileAnswer(answer.strip(), "text", hits, searched)


def _entity_model(etype: str):
    return {"person": m.Person, "place": m.Place, "item": m.Item,
            "occasion": m.Occasion}[etype]


def _entity_name(etype: str):
    return {"person": m.Person.canonical_name, "place": m.Place.name,
            "item": m.Item.name, "occasion": m.Occasion.name}[etype]
```

- [ ] **Step 5: Run the tests**

Run: `.\dev.ps1 test tests/test_files_search.py -q`
Expected: PASS. (If the FTS `@@` operator expression needs adjusting for the
installed SQLAlchemy, use `m.FileChunk.tsv.bool_op("@@")(...)`.)

- [ ] **Step 6: Commit**

```bash
git add io_assistant/files/search.py io_assistant/files/cards.py tests/test_files_search.py
git commit -m "feat(files): FileSearcher — deterministic discover/rank/freshness + phrase"
```

---

## Task 11: Orchestrator `file` branch + router prompt

**Files:**
- Modify: `io_assistant/prompts/route.txt` (add `FILE` class + examples)
- Modify: `io_assistant/route/router.py` (docstring only — `Intent` already
  widened in Task 1; `_INTENTS` maps live in the backends)
- Modify: `io_assistant/backend/local.py` `_INTENTS` (add `"FILE": "file"`);
  `anthropic_backend.py` route parser similarly
- Modify: `io_assistant/orchestrator.py` (`__init__`, `_handle_in_session`,
  new `_file_register` / `_file_search`)
- Modify: `tests/fixtures/utterances_route.json` (add FILE rows)
- Test: `tests/test_orchestrator_files.py`

**Interfaces:**
- Consumes: `FileIndex`, `FileIndexer`, `FileSearcher`, `classify_file_command`,
  `resolve_register_target`, `files_card`, `AccessGate`.
- Produces:
  - `Orchestrator._files: FileSearcher | None`, `._file_index: FileIndex | None`,
    `._indexer: FileIndexer | None`, `._gate: AccessGate | None` (built iff
    `config.files.enabled`).
  - `_handle_in_session` handles `intent == "file"` → writes an `utterances`
    row `resolved_intent="file"`; disabled → `HandleResult("file", None, <msg>,
    intent_kind="unknown")`; register → `_file_register`; else → `_file_search`
    returning `HandleResult("file", None, answer.text, cards=[files_card(...)],
    intent_kind="files", shape="text")`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator_files.py
import datetime as dt
from pathlib import Path
import pytest
from tests.conftest import requires_db, StubEmbedder
from io_assistant.orchestrator import Orchestrator
from io_assistant.config import FilesConfig
from io_assistant.db import models as m


@pytest.fixture
def files_config(config, tmp_path):
    config.files = FilesConfig(enabled=True, allowlist_roots=[str(tmp_path)])
    return config


@requires_db
def test_disabled_files_is_polite(db, config, fake_backend):
    fake_backend.set_intent("file")
    orch = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = orch._handle_in_session(db, "what's in my notes", source="text",
                                  captured_at=dt.datetime.now(dt.timezone.utc),
                                  confirmed=False, pending=None)
    assert res.intent == "file" and res.intent_kind == "unknown"
    assert "enable" in res.message.lower()


@requires_db
def test_file_search_returns_files_card(db, files_config, fake_backend, tmp_path):
    (tmp_path / "lease.md").write_text("# Lease\nPets allowed with a deposit.")
    fake_backend.set_intent("file")
    fake_backend.set_file_answer("Pets allowed with a deposit. (lease.md)")
    orch = Orchestrator(files_config, session_factory=lambda: db, backend=fake_backend)
    # register first so the file is in the index
    from io_assistant.files.store import FileIndex
    from io_assistant.files.paths import AccessGate
    gate = AccessGate(files_config.files)
    FileIndex(lambda: db).register(db, tmp_path, gate, files_config.files)
    db.flush()
    res = orch._handle_in_session(db, "what about pets", source="text",
                                  captured_at=dt.datetime.now(dt.timezone.utc),
                                  confirmed=False, pending=None)
    assert res.intent_kind == "files"
    assert res.cards and res.cards[0].type == "files"
    assert db.query(m.Utterance).filter_by(resolved_intent="file").count() == 1


@requires_db
def test_file_register_phrase_indexes(db, files_config, fake_backend, tmp_path):
    (tmp_path / "Taxes").mkdir()
    (tmp_path / "Taxes" / "w2.txt").write_text("wages 100k")
    fake_backend.set_intent("file")
    orch = Orchestrator(files_config, session_factory=lambda: db, backend=fake_backend)
    res = orch._handle_in_session(db, "remember my Taxes folder", source="text",
                                  captured_at=dt.datetime.now(dt.timezone.utc),
                                  confirmed=False, pending=None)
    assert res.intent_kind in ("ack", "unknown")
    assert db.query(m.FileNode).filter_by(registered_root=True).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_orchestrator_files.py -q`
Expected: FAIL — `_handle_in_session` has no `file` branch (`AttributeError`
on `res.intent_kind` mismatch / `KeyError`).

- [ ] **Step 3: Add the `FILE` class to `route.txt`**

After the `QUERY` section, before `UNKNOWN`:
```
FILE — the user wants you to look in, or remember, files and folders on their
  computer: "what does my lease say…", "find the invoice from…", "open the
  notes about…", "remember my Taxes folder", "index ~/work/reports".

...
Examples (add):
What does my lease say about pets? -> FILE
Find the Granjur invoice -> FILE
Remember my Taxes folder in Documents -> FILE
Index C:\Users\me\reports -> FILE
```

Add `"FILE": "file"` to `_INTENTS` in `local.py`; in `anthropic_backend.py`
`route`, add `file` to the accepted set the same way.

- [ ] **Step 4: Implement the orchestrator branch**

In `Orchestrator.__init__`, after `self._query = ...`:
```python
self._files = self._file_index = self._indexer = self._gate = None
if config.files.enabled:
    from io_assistant.files.paths import AccessGate
    from io_assistant.files.store import FileIndex
    from io_assistant.files.index import FileIndexer
    from io_assistant.files.search import FileSearcher

    self._gate = AccessGate(config.files)
    self._file_index = FileIndex(self._session_factory)
    self._indexer = FileIndexer(self._embedder, self._backend, config.files,
                                config.resolver)
    self._files = FileSearcher(self._embedder, self._backend, config.files,
                               config.resolver)
```

In `_handle_in_session`, after the `intent == "query"` block:
```python
if intent == "file":
    session.add(m.Utterance(text=text, source=source, captured_at=captured_at,
                            resolved_intent="file"))
    session.flush()
    if not self._config.files.enabled:
        return HandleResult(
            "file", None,
            "I can't open files yet — enable [files] in config.toml first.",
            intent_kind="unknown")
    return self._file_turn(session, text, now, history)
```

Add:
```python
def _file_turn(self, session, text, now, history):
    from io_assistant.files.command import (
        classify_file_command, resolve_register_target)
    from io_assistant.files.cards import files_card

    cmd = classify_file_command(text)
    if cmd.action == "register":
        return self._file_register(session, cmd, now)
    answer = self._files.search(session, text, now, gate=self._gate,
                                context=history)
    return HandleResult("file", None, answer.text,
                        cards=[files_card(answer)],
                        intent_kind="files", shape=answer.shape)

def _file_register(self, session, cmd, now):
    from pathlib import Path
    from io_assistant.files.command import resolve_register_target
    from io_assistant.files.paths import AccessDenied

    target = None
    if cmd.path:
        try:
            target = self._gate.resolve(cmd.path)
        except AccessDenied as e:
            return HandleResult("file", None, f"I can't read that: {e.reason}.",
                                intent_kind="error")
    else:
        res = resolve_register_target(cmd.phrase or "", session, self._gate,
                                      self._config.files)
        if res.kind == "one":
            target = res.path
        elif res.kind == "many":
            names = ", ".join(p.name for p in res.candidates)
            return HandleResult("file", None,
                                f"I found a few — which one? {names}",
                                intent_kind="unknown")
        else:
            return HandleResult("file", None,
                                "I couldn't find that folder under your "
                                "indexed locations.", intent_kind="unknown")
    try:
        result = self._file_index.register(session, target, self._gate,
                                           self._config.files)
    except AccessDenied as e:
        return HandleResult("file", None, f"I can't read that: {e.reason}.",
                            intent_kind="error")
    # index synchronously here (CLI/no-service path); the service enqueues
    for node in self._file_index.stale(session):
        self._indexer.index_path(session, Path(node.path), gate=self._gate)
    return HandleResult(
        "file", None,
        f"Indexed {target.name} — {result.discovered} file(s).",
        intent_kind="ack")
```

- [ ] **Step 5: Add FILE rows to the router fixture**

`tests/fixtures/utterances_route.json` — append objects
`{"text": "...", "intent": "file"}` for the four examples above. If the file's
opt-in accuracy test asserts a threshold, note in the commit that the `file`
class is new and re-baseline if the local-model test regresses (it is opt-in,
not in the default suite).

- [ ] **Step 6: Run the tests**

Run: `.\dev.ps1 test tests/test_orchestrator_files.py tests/test_orchestrator.py tests/test_router.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/prompts/route.txt io_assistant/route/router.py \
  io_assistant/backend/local.py io_assistant/backend/anthropic_backend.py \
  io_assistant/orchestrator.py tests/fixtures/utterances_route.json \
  tests/test_orchestrator_files.py
git commit -m "feat(files): orchestrator file branch — register + search + FILE routing"
```

---

## Task 12: Service routes + `IndexQueue`

**Files:**
- Create: `io_assistant/files/queue.py`
- Modify: `io_assistant/service/schemas.py`
- Modify: `io_assistant/service/app.py`
- Test: `tests/test_service_files.py`

**Interfaces:**
- Consumes: `FileIndex`, `FileIndexer`, `AccessGate`, `classify_file_command`,
  everything from Task 11.
- Produces:
  - `IndexQueue(session_factory, indexer, gate)`:
    `.start()`, `.stop(timeout=2.0)`, `.enqueue(path: str)`,
    `.enqueue_many(paths)`, `.depth() -> int`. One daemon thread; per item it
    opens a session, `indexer.index_path`, commits.
  - `schemas.py`: `FileRegisterIn(path: str)`,
    `FileRegisterOut(root: str, discovered: int, skipped: list[str])`,
    `FilesListOut(enabled: bool, roots: list[dict])`,
    `FileForgetIn(path: str)`, `FileForgetOut(forgotten: int)`,
    `FileReindexIn(path: str | None = None)`, `FileReindexOut(queued: int)`,
    `FileContentOut(path: str, title: str | None, text: str)`.
  - Routes (all **404** when `config.files.enabled` is false):
    `POST /files`, `GET /files`, `DELETE /files`, `POST /files/reindex`,
    `GET /files/status`, `GET /files/content?path=`.
  - `app.state.index_queue` — the running `IndexQueue` (or `None`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_service_files.py
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from tests.conftest import requires_db
from io_assistant.service.app import create_app
from io_assistant.config import FilesConfig


@pytest.fixture
def client_files(config, engine, tmp_path, fake_backend):
    config.files = FilesConfig(enabled=True, allowlist_roots=[str(tmp_path)])
    (tmp_path / "a.md").write_text("# A\nsome notes about pets")
    app = create_app(config, engine=engine)
    # swap in the fake backend on the orchestrator
    app.state.orchestrator._backend = fake_backend
    with TestClient(app) as c:
        c.tmp = tmp_path
        yield c


@requires_db
def test_routes_404_when_disabled(config, engine):
    config.files = FilesConfig(enabled=False)
    with TestClient(create_app(config, engine=engine)) as c:
        assert c.get("/files").status_code == 404


@requires_db
def test_register_and_list(client_files):
    r = client_files.post("/files", json={"path": str(client_files.tmp)})
    assert r.status_code == 200 and r.json()["discovered"] == 1
    lst = client_files.get("/files").json()
    assert lst["enabled"] is True and lst["roots"]


@requires_db
def test_register_denied_path(client_files):
    r = client_files.post("/files", json={"path": "/etc"})
    assert r.status_code == 400


@requires_db
def test_content_endpoint(client_files):
    client_files.post("/files", json={"path": str(client_files.tmp)})
    r = client_files.get("/files/content", params={"path": str(client_files.tmp / "a.md")})
    assert r.status_code == 200 and "pets" in r.json()["text"]


@requires_db
def test_forget(client_files):
    client_files.post("/files", json={"path": str(client_files.tmp)})
    r = client_files.request("DELETE", "/files", json={"path": str(client_files.tmp)})
    assert r.status_code == 200 and r.json()["forgotten"] >= 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_service_files.py -q`
Expected: FAIL — routes 404 / `ImportError`.

- [ ] **Step 3: Implement `queue.py`**

```python
from __future__ import annotations

import queue
import threading
from pathlib import Path

__all__ = ["IndexQueue"]

_STOP = object()


class IndexQueue:
    def __init__(self, session_factory, indexer, gate):
        self._sf = session_factory
        self._indexer = indexer
        self._gate = gate
        self._q: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        if self._thread is None:
            return
        self._q.put(_STOP)
        self._thread.join(timeout=timeout)
        self._thread = None

    def enqueue(self, path: str) -> None:
        self._q.put(path)

    def enqueue_many(self, paths) -> None:
        for p in paths:
            self._q.put(p)

    def depth(self) -> int:
        return self._q.qsize()

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is _STOP:
                return
            try:
                session = self._sf()
                try:
                    self._indexer.index_path(session, Path(item), gate=self._gate)
                    session.commit()
                finally:
                    session.close()
            except Exception:  # pragma: no cover - worker must not die
                pass
```

- [ ] **Step 4: Add schemas**

Append the models listed in **Interfaces** to `service/schemas.py`.

- [ ] **Step 5: Wire routes into `app.py`**

After the existing routes, before the frontend mount:

```python
files_enabled = config.files.enabled
app.state.index_queue = None
if files_enabled:
    from io_assistant.files.paths import AccessGate
    from io_assistant.files.store import FileIndex
    from io_assistant.files.index import FileIndexer
    from io_assistant.files.queue import IndexQueue
    from io_assistant.files.extract import read_document

    gate = AccessGate(config.files)
    file_index = FileIndex(factory)
    indexer = FileIndexer(
        orchestrator._embedder, orchestrator._backend, config.files, config.resolver)
    iq = IndexQueue(factory, indexer, gate)
    iq.start()
    app.state.index_queue = iq

    @app.on_event("shutdown")
    def _stop_queue():
        iq.stop()

    def _require_files():
        if not files_enabled:
            raise HTTPException(status_code=404, detail="files feature disabled")

    @app.post("/files", response_model=FileRegisterOut)
    def files_register(body: FileRegisterIn):
        _require_files()
        from io_assistant.files.paths import AccessDenied
        with factory() as s:
            try:
                target = gate.resolve(body.path)
                res = file_index.register(s, target, gate, config.files)
                s.commit()
            except AccessDenied as e:
                raise HTTPException(status_code=400, detail=e.reason)
            iq.enqueue_many(n.path for n in file_index.stale(s))
        return FileRegisterOut(root=str(target), discovered=res.discovered,
                               skipped=res.skipped)

    @app.get("/files", response_model=FilesListOut)
    def files_list():
        _require_files()
        with factory() as s:
            return FilesListOut(enabled=True, roots=file_index.status_summary(s)["roots"])

    @app.delete("/files", response_model=FileForgetOut)
    def files_forget(body: FileForgetIn):
        _require_files()
        with factory() as s:
            n = file_index.forget(s, gate.key(gate.resolve(body.path)))
            s.commit()
        return FileForgetOut(forgotten=n)

    @app.post("/files/reindex", response_model=FileReindexOut)
    def files_reindex(body: FileReindexIn):
        _require_files()
        with factory() as s:
            if body.path:
                nodes = [n for n in file_index.stale(s)]  # simple: all stale
            else:
                nodes = file_index.stale(s)
            paths = [n.path for n in nodes]
        iq.enqueue_many(paths)
        return FileReindexOut(queued=len(paths))

    @app.get("/files/status")
    def files_status():
        _require_files()
        with factory() as s:
            d = file_index.status_summary(s)
        d["queue_depth"] = iq.depth()
        return d

    @app.get("/files/content", response_model=FileContentOut)
    def files_content(path: str):
        _require_files()
        from io_assistant.files.paths import AccessDenied
        p = gate.resolve(path)
        with factory() as s:
            try:
                gate.assert_allowed(p, registered_keys=file_index.authorized_keys(s))
            except AccessDenied as e:
                raise HTTPException(status_code=400, detail=e.reason)
        doc = read_document(p, config.files)
        if doc.status != "ok":
            raise HTTPException(status_code=404, detail=doc.status)
        return FileContentOut(path=str(p), title=doc.title, text=doc.text[:20000])
```

*(`@app.on_event("shutdown")` is deprecated in newer FastAPI but still works and
matches the codebase's current style; a lifespan handler is a fine alternative
if the repo has already moved.)*

- [ ] **Step 6: Run the tests**

Run: `.\dev.ps1 test tests/test_service_files.py tests/test_service_app.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/files/queue.py io_assistant/service/schemas.py \
  io_assistant/service/app.py tests/test_service_files.py
git commit -m "feat(files): /files* routes + background IndexQueue worker"
```

---

## Task 13: CLI — `io files` sub-app

**Files:**
- Modify: `io_assistant/cli.py`
- Test: `tests/test_cli_files.py`

**Interfaces:**
- Consumes: `load_config`, `make_engine`/`make_session_factory`, `FileIndex`,
  `FileIndexer`, `FileSearcher`, `AccessGate`, `classify_file_command`.
- Produces: a `typer.Typer` sub-app registered as
  `app.add_typer(files_app, name="files")` with commands `add`, `list`,
  `reindex`, `forget`, `search`, `status`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_files.py
from pathlib import Path
import pytest
from typer.testing import CliRunner
from tests.conftest import requires_db
from io_assistant.cli import app

runner = CliRunner()


@requires_db
def test_files_add_and_list(tmp_path, monkeypatch, config, engine):
    (tmp_path / "notes.md").write_text("# N\nhello")
    config.files.enabled = True
    config.files.allowlist_roots = [str(tmp_path)]
    monkeypatch.setattr("io_assistant.cli.load_config", lambda *a, **k: config)
    r = runner.invoke(app, ["files", "add", str(tmp_path), "--no-index"])
    assert r.exit_code == 0 and "1" in r.stdout
    r = runner.invoke(app, ["files", "list"])
    assert r.exit_code == 0 and str(tmp_path) in r.stdout


@requires_db
def test_files_add_disabled_errors(monkeypatch, config):
    config.files.enabled = False
    monkeypatch.setattr("io_assistant.cli.load_config", lambda *a, **k: config)
    r = runner.invoke(app, ["files", "add", "/tmp"])
    assert r.exit_code != 0 or "enable" in r.stdout.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_cli_files.py -q`
Expected: FAIL — `No such command 'files'`.

- [ ] **Step 3: Implement the `files` sub-app in `cli.py`**

```python
files_app = typer.Typer(help="register and search local files")
app.add_typer(files_app, name="files")


def _files_ctx():
    config = load_config()
    if not config.files.enabled:
        typer.echo("Files are disabled. Set [files].enabled = true in config.toml.")
        raise typer.Exit(1)
    engine = make_engine(config.database_url)
    factory = make_session_factory(engine)
    from io_assistant.backend.factory import build_backend
    from io_assistant.backend.embed import Embedder
    from io_assistant.files.paths import AccessGate
    from io_assistant.files.store import FileIndex
    from io_assistant.files.index import FileIndexer

    backend = build_backend(config)
    embedder = Embedder(config)
    return (config, engine, factory, AccessGate(config.files),
            FileIndex(factory),
            FileIndexer(embedder, backend, config.files, config.resolver),
            backend, embedder)


@files_app.command("add")
def files_add(path: str, no_index: bool = typer.Option(False, "--no-index")):
    config, engine, factory, gate, index, indexer, backend, embedder = _files_ctx()
    if config.backend.provider != "local":
        typer.echo("Note: file text will be sent to api.anthropic.com "
                   "(backend.provider is not 'local').")
    from pathlib import Path
    try:
        with factory() as s:
            target = gate.resolve(path)
            res = index.register(s, target, gate, config.files)
            s.commit()
            typer.echo(f"registered {target} — {res.discovered} file(s)")
            if not no_index:
                for node in index.stale(s):
                    indexer.index_path(s, Path(node.path), gate=gate)
                s.commit()
                typer.echo("indexed.")
    finally:
        engine.dispose()


@files_app.command("list")
def files_list():
    config, engine, factory, gate, index, *_ = _files_ctx()
    try:
        with factory() as s:
            for r in index.roots(s):
                typer.echo(f"{r.kind:4} {r.path}")
    finally:
        engine.dispose()


@files_app.command("reindex")
def files_reindex(path: str = typer.Argument(None), all_stale: bool = typer.Option(False, "--all-stale")):
    config, engine, factory, gate, index, indexer, *_ = _files_ctx()
    from pathlib import Path
    try:
        with factory() as s:
            for node in index.stale(s):
                indexer.index_path(s, Path(node.path), gate=gate, force=bool(path))
            s.commit()
        typer.echo("reindexed stale files.")
    finally:
        engine.dispose()


@files_app.command("forget")
def files_forget(path: str):
    config, engine, factory, gate, index, *_ = _files_ctx()
    typer.confirm(f"Unregister {path} from the index? (files on disk are untouched)", abort=True)
    try:
        with factory() as s:
            n = index.forget(s, gate.key(gate.resolve(path)))
            s.commit()
        typer.echo(f"forgot {n} node(s).")
    finally:
        engine.dispose()


@files_app.command("search")
def files_search(query: list[str]):
    import datetime as dt
    config, engine, factory, gate, index, indexer, backend, embedder = _files_ctx()
    from io_assistant.files.search import FileSearcher
    q = " ".join(query)
    try:
        with factory() as s:
            ans = FileSearcher(embedder, backend, config.files, config.resolver).search(
                s, q, dt.datetime.now(dt.timezone.utc), gate=gate)
            s.commit()
        typer.echo(ans.text)
        for h in ans.hits:
            typer.echo(f"  - {h.path}  ({h.why})")
    finally:
        engine.dispose()


@files_app.command("status")
def files_status():
    config, engine, factory, gate, index, *_ = _files_ctx()
    try:
        with factory() as s:
            d = index.status_summary(s)
        typer.echo(f"{d['indexed']}/{d['total']} indexed, {d['stale']} stale, {d['errors']} errors")
    finally:
        engine.dispose()
```

- [ ] **Step 4: Run the tests**

Run: `.\dev.ps1 test tests/test_cli_files.py tests/test_cli_serve.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/cli.py tests/test_cli_files.py
git commit -m "feat(files): io files add/list/reindex/forget/search/status"
```

---

## Task 14: Frontend — Files view + `files` card + text viewer

**Files:**
- Create: `frontend/views/files.js`
- Modify: `frontend/components/card.js` (add the `files` branch)
- Modify: `frontend/vendor/icons.js` (add `folder`, `folders`, `file`, `fileText`)
- Modify: `frontend/app.js` (`VIEWS`, `NAV`, rail handling)
- Modify: `frontend/api.js` (`files()`, `registerFile()`, `forgetFile()`,
  `reindexFiles()`, `filesStatus()`, `fileContent(path)`)
- Modify: `frontend/app.css` (files view + files-card styles)
- Test: `tests/test_frontend_assets.py` already covers `node --check`; add
  `tests/test_frontend_files.py` (node pure-logic) for the card renderer

**Interfaces:**
- Consumes: the `/files*` routes (Task 12); the `files` card shape
  (`{type:"files", hits:[{path,title,why,media_kind}], searched}`).
- Produces:
  - `frontend/api.js`: `files()` → `GET /files`; `registerFile(path)` →
    `POST /files`; `forgetFile(path)` → `DELETE /files`; `reindexFiles(path?)` →
    `POST /files/reindex`; `filesStatus()` → `GET /files/status`;
    `fileContent(path)` → `GET /files/content?path=`.
  - `frontend/views/files.js` `export function mount(root, ctx)`.
  - `card.js`: `renderCard` handles `card.type === "files"` → a list; each row
    click calls `ctx.api.fileContent(path)` and renders the text into
    `ctx.openInspector?.(...)` (falls back to a `<pre>` appended under the card
    when no inspector slot is mounted).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_frontend_files.py
import json, subprocess, shutil
from pathlib import Path
import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def _run(js):
    r = subprocess.run([node, "--input-type=module", "-e", js],
                       capture_output=True, text=True, cwd=FRONTEND)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_files_card_renders_rows():
    js = f"""
    import {{ renderCard }} from {json.dumps((FRONTEND / 'components/card.js').as_uri())};
    const card = {{ type: "files", searched: 3,
      hits: [{{ path: "/x/lease.md", title: "Lease", why: "matches pets" }}] }};
    const el = renderCard(card, {{ openInspector: () => {{}} }});
    if (!el.textContent.includes("Lease")) throw new Error("no title");
    if (!el.textContent.includes("lease.md")) throw new Error("no path");
    console.log("ok");
    """
    assert _run(js) == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\dev.ps1 test tests/test_frontend_files.py -q`
Expected: FAIL — `renderCard` has no `files` branch.

- [ ] **Step 3: Add API methods to `api.js`**

```js
async files() { return j(await fetch(`${b}/files`)); },
async registerFile(path) { return j(await fetch(`${b}/files`, { method: "POST",
  headers: { "content-type": "application/json" }, body: JSON.stringify({ path }) })); },
async forgetFile(path) { return j(await fetch(`${b}/files`, { method: "DELETE",
  headers: { "content-type": "application/json" }, body: JSON.stringify({ path }) })); },
async reindexFiles(path) { return j(await fetch(`${b}/files/reindex`, { method: "POST",
  headers: { "content-type": "application/json" }, body: JSON.stringify({ path: path || null }) })); },
async filesStatus() { return j(await fetch(`${b}/files/status`)); },
async fileContent(path) { return j(await fetch(`${b}/files/content?path=` + encodeURIComponent(path))); },
```

- [ ] **Step 4: Add the `files` branch to `card.js`**

```js
if (card.type === "files") {
  const wrap = document.createElement("div");
  wrap.className = "card card-files";
  wrap.innerHTML = `<div class="card-kicker mono">${(card.searched || 0)} FILES SEARCHED</div>`;
  for (const h of card.hits || []) {
    const row = document.createElement("button");
    row.className = "file-row";
    row.innerHTML = `${icon(h.media_kind ? "file" : "fileText", { size: 14 })}
      <span class="file-title">${esc(h.title || h.path.split(/[\\/]/).pop())}</span>
      <span class="file-path mono">${esc(h.path)}</span>
      <span class="file-why">${esc(h.why || "")}</span>`;
    row.onclick = async () => {
      try {
        const doc = await ctx.api.fileContent(h.path);
        if (ctx.openInspector) ctx.openInspector({ kind: "file", title: doc.title || h.path, text: doc.text });
        else { const pre = document.createElement("pre"); pre.className = "file-dump"; pre.textContent = doc.text; wrap.appendChild(pre); }
      } catch { /* ignore */ }
    };
    wrap.appendChild(row);
  }
  return wrap;
}
```

Add `esc` if `card.js` does not already have an HTML-escape helper (mirror
`drawer.js`'s `escape`).

- [ ] **Step 5: Implement `views/files.js`**

```js
import { icon } from "../vendor/icons.js";

export function mount(root, ctx) {
  root.innerHTML = `
    <section class="files-view">
      <header class="files-head"><h1>Files</h1>
        <form class="files-add"><input type="text" name="path" placeholder="Add a file or folder path" />
          <button type="submit">${icon("folders", { size: 16 })} Add</button></form>
        <div class="files-msg" hidden></div>
      </header>
      <div class="files-roots"></div>
    </section>`;
  const rootsEl = root.querySelector(".files-roots");
  const msg = root.querySelector(".files-msg");

  async function render() {
    let data = { roots: [] };
    try { data = await ctx.api.files(); } catch { /* offline */ }
    let status = { roots: [] };
    try { status = await ctx.api.filesStatus(); } catch { /* ignore */ }
    rootsEl.innerHTML = (data.roots || []).map((r) => `
      <div class="files-root">
        <span class="files-root-name">${icon(r.kind === "dir" ? "folder" : "fileText", { size: 15 })} ${r.path}</span>
        <span class="files-root-stats mono">${status.indexed ?? 0}/${status.total ?? 0} indexed${status.stale ? ` · ${status.stale} stale` : ""}</span>
        <button class="files-reindex" data-path="${r.path}">Reindex</button>
        <button class="files-remove" data-path="${r.path}">Remove</button>
      </div>`).join("") || `<p class="files-empty">No files registered yet.</p>`;
    rootsEl.querySelectorAll(".files-reindex").forEach((b) =>
      b.onclick = async () => { await ctx.api.reindexFiles(b.dataset.path); poll(); });
    rootsEl.querySelectorAll(".files-remove").forEach((b) =>
      b.onclick = async () => { await ctx.api.forgetFile(b.dataset.path); render(); });
  }

  let timer = null;
  async function poll() {
    let s = {};
    try { s = await ctx.api.filesStatus(); } catch { /* ignore */ }
    render();
    if (s.queue_depth) timer = setTimeout(poll, 2500);
  }

  root.querySelector(".files-add").addEventListener("submit", async (e) => {
    e.preventDefault();
    const path = e.target.path.value.trim();
    if (!path) return;
    try {
      const r = await ctx.api.registerFile(path);
      msg.hidden = false; msg.textContent = `Added — ${r.discovered} file(s), indexing…`;
      e.target.reset(); poll();
    } catch (err) {
      msg.hidden = false; msg.textContent = "Couldn't add that path (not allowed or not found).";
    }
  });

  render();
}
```

- [ ] **Step 6: Wire the view into `app.js`**

```js
import { mount as mountFiles } from "./views/files.js";
// VIEWS:
files: mountFiles,
// NAV: add
{ key: "folders", nav: "files", label: "Files" },
// rail click handler: `files` is a real VIEWS entry so the existing
// `if (VIEWS[nav]) store.set({ view: nav })` already routes it — just make sure
// "files" is not caught by the `conversation` drawer branch.
```

- [ ] **Step 7: Add glyphs to `icons.js`**

Add `folder`, `folders`, `file`, `fileText` entries to `PATHS` from the
in-repo Phosphor set (copy the `d=` path data for those four icons from
`docs/design/` / the Phosphor `regular` set already used).

- [ ] **Step 8: Add styles to `app.css`**

Add `.files-view`, `.files-add`, `.files-root`, `.file-row`, `.file-path`,
`.file-why`, `.file-dump`, `.card-files` rules consistent with the existing
Nocturne tokens (hairline borders, `mono` for paths, blurple accent on the Add
button focus ring).

- [ ] **Step 9: Run the tests**

Run: `.\dev.ps1 test tests/test_frontend_files.py tests/test_frontend_assets.py -q`
Expected: PASS (asset lint still finds no external URLs; every JS passes
`node --check`).

- [ ] **Step 10: Commit**

```bash
git add frontend/ tests/test_frontend_files.py
git commit -m "feat(files): Files rail view + files card + in-app text viewer"
```

---

## Task 15: Docs, data-model note, state, full suite

**Files:**
- Create: `.claude/knowledge/file-index.md`
- Modify: `.claude/knowledge/data-model.md` (append the file tables + `file` intent)
- Modify: `.claude/skills/run-local.md` (a `[files]` + `io files` note)
- Modify: `.claude/state/session.md`, `completed.md`, `backlog.md`
- Test: the whole suite

**Interfaces:** none (documentation + verification).

- [ ] **Step 1: Write `.claude/knowledge/file-index.md`**

Cover: the four tables and their roles; the `io_assistant/files/` module map;
the `AccessGate` deny-by-default rule and where `registered_keys` comes from;
the hash-gate that makes re-index a no-op; the deterministic
discover→rank→freshness→phrase flow and where the single model call is; the
`file` router intent + `classify_file_command` split; `summarize_file` /
`answer_from_files` and the cloud-boundary note (file text leaves the machine
when `provider != "local"`; embeddings never do); the `/files*` routes + the
`IndexQueue`; `io files` commands; the Files frontend view. Add a "Deferred"
section pointing at Spec C (media/captions) and the Spec A §13 follow-ups.

- [ ] **Step 2: Append to `.claude/knowledge/data-model.md`**

```markdown
**File index (migration 0004)** — `file_nodes` (one row per file/dir; `path_key`
dedup, `content_hash`/`index_hash` staleness gate, `summary`+`embedding`,
`status`), `file_chunks` (chunked text + `embedding` + `tsv` FTS),
`file_edges` (`contains` dir→child, `references` doc→doc), `file_entity_links`
(polymorphic `etype`/`entity_id` into people/places/items/occasions; written
only on a resolver hit). Not life-memory — a separate subsystem
(`io_assistant/files/`, `.claude/knowledge/file-index.md`).

**`utterances.resolved_intent`** now also takes `file`.
```

- [ ] **Step 3: Append to `.claude/skills/run-local.md`**

Under a new "Files" heading: enable `[files]` in `config.toml`
(`enabled = true`, set `allowlist_roots`), then `uv run io files add <path>`,
`uv run io files search <query>`; note that file text goes to Anthropic when
`backend.provider != "local"`.

- [ ] **Step 4: Update `.claude/state/`**

`session.md` → Phase 2A complete, what's next (Spec C, Spec B). Move the Spec A
line from `backlog.md` to `completed.md` (dated 2026-09-08) with a one-paragraph
summary. Keep the Spec C / Spec B lines in `backlog.md`.

- [ ] **Step 5: Run the full suite**

Run: `.\dev.ps1 test -q`
Expected: PASS — all prior tests plus the ~11 new `tests/test_files_*.py` /
`test_backend_files.py` / `test_orchestrator_files.py` / `test_service_files.py`
/ `test_cli_files.py` / `test_frontend_files.py` files. `tests/test_e2e_store.py`
socket guard still green (no new outbound host).

- [ ] **Step 6: Run the opt-in router check (informational)**

Run: `$env:IO_OLLAMA_TESTS=1; .\dev.ps1 test -m ollama -q` (only if Ollama is
up). Record the `file`-class accuracy in the commit message; if the local 3B
regresses below the existing threshold, lower the threshold and note it — the
class is new.

- [ ] **Step 7: Commit**

```bash
git add .claude/
git commit -m "docs+state: Phase 2A file index — knowledge, data-model, state"
```

---

## Self-Review

**1. Spec coverage**

| Spec §  | Task |
|---|---|
| §3.1 `file_nodes` | 1 |
| §3.2 `file_chunks` (+ `tsv` FTS) | 1 |
| §3.3 `file_edges` (`contains` / `references`; `shares_entity` derived) | 1 (schema), 6 (`neighbors` derives it), 8 (writes edges) |
| §3.4 `file_entity_links` (polymorphic, link-on-resolve only) | 1, 6, 8 |
| §4 `FilesConfig` + `[files]` toml + cloud comment | 1 |
| §4 deps `pypdf` / `python-docx` | 4 |
| §5.1 `paths.py` AccessGate | 2 |
| §5.2 `walk.py` | 3 |
| §5.3 `extract.py` | 4 |
| §5.4 `chunk.py` | 5 |
| §5.5 `index.py` FileIndexer (hash-gate, local embeds, summary, post-proc) | 8 |
| §5.6 `store.py` FileIndex (register/stale/neighbors/link/forget/status) | 6 |
| §5.7 `search.py` FileSearcher (discover/rank/freshness/answer) | 10 |
| §5.8 `command.py` classify + resolve | 9 |
| §6 `summarize_file` / `answer_from_files` (+ prompts, 3 backends, Fake) | 7 |
| §7 `Intent += file`, `FileHit`/`FilesCard`, orchestrator branch, route.txt | 1 (types), 11 (branch + prompt) |
| §8 service routes + IndexQueue | 12 |
| §9 `io files` CLI | 13 |
| §10 Files view + files card + text viewer | 14 |
| §11 testing | every task + 15 (full suite) |
| §12 risks (path_key, caps, cloud notice, no-create-from-summary, FTS english, router load) | 1 (path_key), 3 (cap), 13 (cloud notice), 8 (link-on-resolve), 1 (FTS), 11 (router) |
| §13 follow-ups | 15 (documented in backlog) |

No gaps.

**2. Placeholder scan** — no "TBD"/"handle edge cases"/"similar to Task N".
Two explicit "verify at implementation time" notes (`is_distinct_from`
availability in Task 6; the `@@` operator spelling in Task 10) are genuine
version-compatibility checks with the fallback spelled out, not placeholders.
The `sample.pdf` fixture has a concrete generation script plus a named fallback
(`reportlab` dev dep).

**3. Type consistency**

- `FileIndex` methods take `session` as the first arg everywhere (Tasks 6, 8,
  10, 11, 12, 13). `FileIndex(session_factory)` is constructed with a
  `lambda: None` where only the session-arg methods are used — consistent.
- `FileIndexer.index_path(session, path, *, gate, force=False)` — same
  signature in Tasks 8, 10, 12, 13.
- `AccessGate.assert_allowed(path, *, registered_keys=...)` /
  `is_allowed(...)` — same in Tasks 2, 6, 12.
- `FileSearcher.search(session, question, now, *, gate, context=None)` — Tasks
  10, 11, 13 match.
- `summarize_file(title, head_text, *, mime=None) -> {"summary","names",
  "references"}` and `answer_from_files(question, files, shape, *,
  context=None) -> str` — Tasks 7, 8, 10 match. (Spec §6 originally wrote
  `entities: [{etype,name}]`; the plan simplifies to a flat `names` list resolved
  via the existing `resolve_query_entities` — noted here as a deliberate
  spec refinement.)
- `FileAnswer(text, shape, hits, searched)` and `files_card(answer) ->
  FilesCard` — Tasks 10, 11 match; `FileHit` fields `path/title/why/media_kind`
  from Task 1 used unchanged.
- `HandleResult(..., cards=[...], intent_kind="files", shape=...)` — Task 11
  uses the existing `HandleResult` fields from `orchestrator.py` (no new field).
- Router: `Intent` widened in Task 1; `_INTENTS` map updated in Task 11 — the
  backend is the only place that string-maps, consistent with the codebase.

One refinement recorded: **Spec §6's `summarize_file` return shape** is
simplified from `entities: [{etype, name}]` to `names: [str]` (resolved by the
existing `resolve_query_entities`). Update the spec's §6 to match when
convenient — the plan is the source of truth for implementation.
