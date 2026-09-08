# IO Backlog Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear the correctness and hygiene debt logged after Plan 1 — the
`Orchestrator` connection leak, the `EntityResolver` full-table scan, the missing
`embedding_dim` guard, and the "deferred minors" bullet — so Plan 2 (query
pipeline) builds on a clean base.

**Architecture:** Seven small, independently-reviewable tasks. Two of them
(`conftest` nested-transaction fixture, then `Orchestrator` session ownership)
are sequenced first because they change test infrastructure every later task
relies on. The rest are isolated single-file fixes with their own tests.

**Tech Stack:** Python 3.11+, `uv`, SQLAlchemy 2.x + Alembic, `psycopg` 3,
`pgvector`, `pg_trgm`, `pydantic` v2, `rapidfuzz`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-07-io-phase-1-design.md` (§3 data model,
§4.2 resolve, §4.3 gate, §4.5 persist). This plan implements review follow-ups,
not new spec surface.

## Global Constraints

- **Python** ≥ 3.11. Dependency management via `uv`; everything runs through
  `uv run` (`uv run pytest`, `uv run alembic`).
- **Local-first:** no outbound network except `localhost` (Postgres, Ollama) and
  `api.anthropic.com` when `backend.provider` is `"anthropic"`/`"hybrid"`.
- **LLM boundary:** the model does route/extract/plan/phrase only. Dedup, date
  arithmetic, ranking, entity identity are deterministic Python.
- **Migrations:** every schema change is an Alembic migration in
  `io_assistant/db/migrations/versions/`. No ad-hoc `ALTER`. Embedding dimension
  is fixed at `config.embedding_dim` / `db.models.EMBED_DIM` = `768`.
- **TDD:** failing test first, watch it fail, minimal implementation, watch it
  pass, commit. Never mock the database — tests run against the real PostgreSQL
  named by `IO_TEST_DATABASE_URL`. Backend calls may use `FakeBackend`; the
  persistence, resolver, and SQL layers never are.
- **Package name** is `io_assistant`. CLI command is `io`.
- DB-touching tests are marked `@requires_db` (`tests/conftest.py`) and skip
  cleanly when `IO_TEST_DATABASE_URL` is unset.

---

## Task 1: Config ↔ EMBED_DIM guard + remove dead import

**Files:**
- Modify: `io_assistant/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: `io_assistant.db.models.EMBED_DIM` (int, currently `768`).
- Produces: `load_config()` raises `ConfigError` when
  `Config.embedding_dim != io_assistant.db.models.EMBED_DIM`. No signature change.

**Background:** `config.py` imports `field_validator` but never uses it. The spec
fixes the embedding dimension; if `config.toml` says `embedding_dim = 512` while
the ORM/migration DDL is `Vector(768)`, the mismatch currently surfaces only as
an opaque pgvector insert error deep in `persist_store`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_config.py`

```python
def test_embedding_dim_must_match_orm(tmp_path):
    p = write_toml(tmp_path, """
        database_url = "postgresql+psycopg://u:p@localhost/db"
        embedding_dim = 512
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
    with pytest.raises(ConfigError, match="embedding_dim"):
        load_config(p)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_embedding_dim_must_match_orm -v`
Expected: FAIL — no exception raised (returns a `Config`).

- [ ] **Step 3: Implement**

In `io_assistant/config.py`:

Change the pydantic import line from
```python
from pydantic import BaseModel, ValidationError, field_validator
```
to
```python
from pydantic import BaseModel, ValidationError
```

Then in `load_config`, after the `Config.model_validate(raw)` block, before
`return`:
```python
    try:
        cfg = Config.model_validate(raw)
    except ValidationError as e:
        raise ConfigError(str(e)) from e

    from io_assistant.db.models import EMBED_DIM

    if cfg.embedding_dim != EMBED_DIM:
        raise ConfigError(
            f"embedding_dim {cfg.embedding_dim} != db.models.EMBED_DIM "
            f"{EMBED_DIM}; changing the embedding dimension needs a migration "
            f"+ backfill (see .claude/rules/migrations.md)"
        )
    return cfg
```
(The import is function-local on purpose: `config.py` is otherwise free of the
SQLAlchemy/pgvector import chain, and several fast unit tests import it alone.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS (all existing cases + the new one).

- [ ] **Step 5: Commit**

```bash
git add io_assistant/config.py tests/test_config.py
git commit -m "fix: config guards embedding_dim against db.models.EMBED_DIM"
```

---

## Task 2: Wrap malformed Ollama responses in `LocalBackendError`

**Files:**
- Modify: `io_assistant/backend/local.py`
- Test: `tests/test_backend_local.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `LocalBackend._chat` raises `LocalBackendError` (not a bare
  `KeyError`) when the Ollama JSON body lacks `message` / `content`.

**Background:** `_chat` returns `resp.json()["message"]["content"]`. On a 200
response whose body is `{"error": "model not found"}` or otherwise
shape-shifted, this raises `KeyError` — which callers (`Extractor`, `Router`)
do not expect and do not catch. Every other failure path here is
`LocalBackendError`.

- [ ] **Step 1: Write the failing test** — add to `tests/test_backend_local.py`

```python
def test_chat_wraps_malformed_body(config, monkeypatch):
    import httpx
    from io_assistant.backend.local import LocalBackend, LocalBackendError

    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"error": "model 'x' not found"}
    class FakeClient:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, *a, **k): return FakeResp()
    monkeypatch.setattr(httpx, "Client", FakeClient)

    with pytest.raises(LocalBackendError):
        LocalBackend(config).route("hello")
```

(If `tests/test_backend_local.py` has no `import pytest`, add it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_backend_local.py::test_chat_wraps_malformed_body -v`
Expected: FAIL — raises `KeyError: 'message'`, not `LocalBackendError`.

- [ ] **Step 3: Implement**

In `io_assistant/backend/local.py`, `_chat`, change the request block:
```python
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(self._url, json=body)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise LocalBackendError(f"ollama chat failed: {e}") from e
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as e:
            raise LocalBackendError(
                f"ollama chat returned an unexpected body: {data!r}"
            ) from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_backend_local.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/backend/local.py tests/test_backend_local.py
git commit -m "fix: LocalBackend wraps malformed Ollama bodies in LocalBackendError"
```

---

## Task 3: `db` fixture uses a nested transaction so committing tests stay isolated

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/test_db_models.py` (add one fixture-behaviour test)

**Interfaces:**
- Consumes: `engine` (session-scoped, already present).
- Produces: an unchanged `db` fixture *contract* (`yield`s a `Session`), but one
  where a `session.commit()` inside a test commits only to a SAVEPOINT that the
  fixture rolls back on teardown. This is the standard SQLAlchemy
  "join an external transaction" recipe and it is a prerequisite for Task 4
  (Orchestrator will call `session.commit()`).

**Background:** the current `db` fixture binds the `Session` straight to a
connection with a single outer transaction. If code under test calls
`session.commit()`, that transaction commits for real and rows leak between
tests. The nested-transaction pattern keeps `commit()` semantics visible to the
code under test while guaranteeing rollback.

- [ ] **Step 1: Write the failing test** — add to `tests/test_db_models.py`

```python
@requires_db
def test_db_fixture_rolls_back_committed_rows(db):
    import datetime as dt
    from io_assistant.db import models as m
    db.add(m.Utterance(text="leak check", source="text",
                        captured_at=dt.datetime.now(dt.timezone.utc)))
    db.commit()  # would leak to other tests without the nested-tx fixture
    assert db.query(m.Utterance).filter_by(text="leak check").count() == 1
```

Then add a second module `tests/test_db_isolation_probe.py`:
```python
from tests.conftest import requires_db
from io_assistant.db import models as m

@requires_db
def test_previous_commit_did_not_leak(db):
    assert db.query(m.Utterance).filter_by(text="leak check").count() == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_db_models.py::test_db_fixture_rolls_back_committed_rows tests/test_db_isolation_probe.py -v`
Expected: `test_previous_commit_did_not_leak` FAILS (count is 1 — the row
leaked).

- [ ] **Step 3: Implement** — replace the `db` fixture body in `tests/conftest.py`

```python
from sqlalchemy import event

@pytest.fixture
def db(engine):
    """Function-scoped session joined to an outer transaction. Commits inside a
    test land on a SAVEPOINT that is rolled back on teardown, so tests that
    exercise real commit() paths stay isolated."""
    connection = engine.connect()
    trans = connection.begin()
    Session = make_session_factory(connection)
    session = Session()
    session.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, transaction):
        if transaction.nested and not transaction._parent.nested:
            sess.begin_nested()

    try:
        yield session
    finally:
        event.remove(session, "after_transaction_end", _restart_savepoint)
        session.close()
        trans.rollback()
        connection.close()
```

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS — the two probe tests now pass, and every existing `@requires_db`
test is unaffected (they never committed before; they still see their flushed
rows).

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_db_models.py tests/test_db_isolation_probe.py
git commit -m "test: db fixture joins an outer transaction so commit() stays isolated"
```

---

## Task 4: `Orchestrator` owns the session per `handle()`; simplify `cli.py`

**Files:**
- Modify: `io_assistant/orchestrator.py`, `io_assistant/cli.py`
- Test: `tests/test_orchestrator_store.py`, `tests/test_persist.py` (add one
  committing durability test), `tests/test_e2e_store.py`

**Interfaces:**
- Consumes: `session_factory: Callable[[], Session]` — now documented as "returns
  a fresh Session that the Orchestrator will commit and close."
- Produces:
  - `Orchestrator.handle(...)` acquires exactly one `Session` from
    `session_factory()`, uses it for the whole call, `commit()`s on the
    success and gated paths, `rollback()`s on an unexpected exception, and
    `close()`s in a `finally`. The verbatim-utterance durability guarantee
    (utterance row survives a `PersistError`) is preserved: `persist_store`
    already flushes the utterance before the write SAVEPOINT, so the commit
    that `handle()` now issues persists it.
  - `cli.py`: `store` and `repl` pass `factory` (the real
    `sessionmaker`) straight through as `session_factory` and no longer
    create / commit / close sessions themselves.

**Background:** `Orchestrator.handle` calls `self._session_factory()` (up to
twice) and never closes the result. With the `lambda: shared_session` that
`cli.py` passes today it happens to be harmless; with a real `sessionmaker`
(Plan 3 FastAPI, and the more honest test wiring) every call leaks a connection.

- [ ] **Step 1: Write the failing durability test** — add to `tests/test_persist.py`

```python
@requires_db
def test_utterance_survives_persist_error_after_commit(engine, config, fake_backend, monkeypatch):
    """A committing end-to-end proof that a failed write pass still leaves the
    verbatim utterance row physically in the database."""
    import datetime as dt
    from sqlalchemy.orm import sessionmaker
    from io_assistant import orchestrator as orch
    from io_assistant.models_domain import ExtractionResult, ExtractedRecord
    from io_assistant.db import models as m

    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(records=[
        ExtractedRecord(kind="event", title="boom", when_phrase="today", confidence=0.9)
    ]))

    class HalfEmbedder:
        def embed_one(self, t):
            if "boom" in t:
                raise RuntimeError("embedding backend down")
            return [0.0] * 768
        def embed(self, ts): return [[0.0] * 768 for _ in ts]
    monkeypatch.setattr(orch, "Embedder", lambda cfg: HalfEmbedder())

    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    o = orch.Orchestrator(config, session_factory=factory, backend=fake_backend)
    res = o.handle("something that will fail to store", source="text",
                   captured_at=dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc))
    assert res.stored is None and "kept a note" in res.message

    check = factory()
    try:
        rows = check.query(m.Utterance).filter_by(
            text="something that will fail to store").all()
        assert len(rows) == 1 and rows[0].resolved_intent == "store"
        # cleanup — this test commits for real, outside the `db` fixture
        for r in rows:
            check.delete(r)
        check.commit()
    finally:
        check.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_persist.py::test_utterance_survives_persist_error_after_commit -v`
Expected: FAIL — `handle()` never commits, so the fresh `check` session sees
zero rows.

- [ ] **Step 3: Implement `Orchestrator`** — `io_assistant/orchestrator.py`

Replace `handle` so it owns one session:
```python
    def handle(
        self,
        text: str,
        *,
        source: str = "text",
        captured_at: datetime | None = None,
        confirmed: bool = False,
        pending: PendingStore | None = None,
    ) -> HandleResult:
        session = self._session_factory()
        try:
            result = self._handle_in_session(
                session, text, source=source, captured_at=captured_at,
                confirmed=confirmed, pending=pending,
            )
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def _handle_in_session(
        self, session, text, *, source, captured_at, confirmed, pending,
    ) -> HandleResult:
        if pending is not None:
            return self._store(
                session,
                text=pending.text,
                source=pending.source,
                captured_at=pending.captured_at,
                now=pending.captured_at,
                extraction=pending.extraction,
                confirmed=True,
                existing_utterance_id=pending.utterance_id,
            )

        if captured_at is None:
            captured_at = datetime.now(timezone.utc)
        now = captured_at

        intent = self._router.classify(text)

        if intent == "unknown":
            return HandleResult(
                "unknown", None,
                "I didn't catch that - please rephrase and try again.",
            )
        if intent == "query":
            return HandleResult(
                "query", None,
                "Query answering isn't available yet (comes in Plan 2).",
            )

        extraction = self._extractor.run(text, now)
        if extraction is None:
            session.add(m.Utterance(
                text=text, source=source, captured_at=captured_at,
                resolved_intent="store", marker="extraction_failed",
            ))
            session.flush()
            return HandleResult(
                "store", None, "I couldn't make sense of that to store it."
            )

        return self._store(
            session, text=text, source=source, captured_at=captured_at,
            now=now, extraction=extraction, confirmed=confirmed,
        )
```
Delete the old body of `handle` (everything from `if pending is not None:` down
to the final `return self._store(...)`); `_store` and `_summarize` are
unchanged. `PersistError` is still swallowed inside `_store` and returned as a
`HandleResult`, so the `except Exception: session.rollback()` in `handle` never
sees it — the utterance row stays flushed and the outer `commit()` persists it.

- [ ] **Step 4: Update `cli.py`**

`store`:
```python
@app.command()
def store(text: str) -> None:
    """Store an utterance."""
    config = load_config()
    engine = make_engine(config.database_url)
    factory = make_session_factory(engine)
    try:
        res = Orchestrator(config, session_factory=factory).handle(text)
    finally:
        engine.dispose()
    print(res.message)
```

`repl` — drop the per-line `session = factory()` / `commit` / `close`; the
Orchestrator now does it:
```python
@app.command()
def repl() -> None:
    """Interactive loop."""
    config = load_config()
    engine = make_engine(config.database_url)
    factory = make_session_factory(engine)
    orch = Orchestrator(config, session_factory=factory)
    pending_store: PendingStore | None = None
    try:
        while True:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            stripped = line.strip()
            if stripped.lower() in {"exit", "quit"}:
                break
            if not stripped:
                continue
            is_confirm = (
                pending_store is not None and stripped.lower() in {"y", "yes"}
            )
            if is_confirm:
                res = orch.handle(pending_store.text, pending=pending_store)
            else:
                res = orch.handle(stripped)
            print(res.message)
            pending_store = res.pending
    finally:
        engine.dispose()
```
(Note `orch.handle(stripped)` — persist the trimmed text, not the raw line;
this also closes the `cli.py` half of the "persist `stripped` not raw `line`"
backlog note. `_make_session_factory` is now unused — delete it.)

- [ ] **Step 5: Update the existing orchestrator / e2e tests to real sessions**

In `tests/test_orchestrator_store.py` and `tests/test_e2e_store.py`, the tests
pass `session_factory=lambda: db` and then assert against `db` after `handle()`
returns. Now that `handle()` commits and closes its session, give them a
factory bound to the same connection as `db` so the committed-to-SAVEPOINT rows
are visible to the `db` session's later queries:

Replace `session_factory=lambda: db` with `session_factory=_conn_factory(db)`
where `_conn_factory` is a new helper in `tests/conftest.py`:
```python
@pytest.fixture
def conn_factory(db):
    """A session factory bound to the same connection as `db`, so a session it
    hands out commits to the shared SAVEPOINT and `db` sees the rows."""
    from io_assistant.db.base import make_session_factory
    bind = db.connection()
    return make_session_factory(bind)
```
and in each test take `conn_factory` as a fixture arg and pass
`session_factory=conn_factory`. The nested-transaction `db` fixture (Task 3)
keeps every such commit inside the rolled-back SAVEPOINT.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS — including the new durability test and all migrated
orchestrator/e2e tests.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/orchestrator.py io_assistant/cli.py tests/
git commit -m "fix: Orchestrator owns one session per handle() (commit+close); cli.py simplified"
```

---

## Task 5: Migration `0002` — aliases default, drop redundant indexes, add resolver trigram indexes; mirror indexes onto the ORM

**Files:**
- Create: `io_assistant/db/migrations/versions/0002_cleanup_and_trgm.py`
- Modify: `io_assistant/db/models.py`
- Test: `tests/test_db_models.py`

**Interfaces:**
- Consumes: revision `0001` (down_revision = `"0001"`, revision = `"0002"`).
- Produces:
  - `people.aliases` / `places.aliases` / `items.aliases` gain
    `server_default = '{}'` (they are already `NOT NULL`; an INSERT that omits
    them currently fails instead of defaulting to an empty array).
  - The redundant b-tree indexes on the *first* column of a composite PK are
    dropped: `ix_record_people_record_id`, `ix_record_places_record_id`,
    `ix_record_items_record_id`, `ix_record_occasions_record_id`,
    `ix_occasion_people_occasion_id` (the PK already indexes a leading-column
    prefix). The *second*-column indexes (`_person_id`, `_place_id`,
    `_item_id`, `_occasion_id`) stay.
  - `CREATE EXTENSION IF NOT EXISTS pg_trgm`, and GIN trigram indexes
    `ix_people_canonical_name_trgm`, `ix_places_name_trgm`,
    `ix_items_name_trgm` on the entity name columns — the index the resolver
    rewrite in Task 6 uses to narrow candidates in SQL instead of scanning.
  - `io_assistant/db/models.py`: every index that exists in the DB is now also
    declared on the ORM model via `__table_args__`, so `alembic check` /
    autogenerate is clean and can gate CI later.

- [ ] **Step 1: Write the failing test** — add to `tests/test_db_models.py`

```python
@requires_db
def test_aliases_column_defaults_to_empty_array(db):
    from sqlalchemy import text as _t
    db.execute(_t("INSERT INTO people (canonical_name) VALUES ('Defaulted')"))
    row = db.execute(_t(
        "SELECT aliases FROM people WHERE canonical_name = 'Defaulted'"
    )).first()
    assert row[0] == []

@requires_db
def test_trigram_and_pk_indexes(db):
    from sqlalchemy import text as _t
    names = {r[0] for r in db.execute(_t(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'"
    ))}
    assert "ix_people_canonical_name_trgm" in names
    assert "ix_record_people_person_id" in names          # kept
    assert "ix_record_people_record_id" not in names      # dropped (PK covers it)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_db_models.py -k "aliases_column_defaults or trigram_and_pk" -v`
Expected: FAIL — no server default; `ix_record_people_record_id` still present;
no trigram index.

- [ ] **Step 3: Write the migration** — `io_assistant/db/migrations/versions/0002_cleanup_and_trgm.py`

```python
"""cleanup: aliases default, drop redundant PK-leading indexes, add pg_trgm

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-08
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_REDUNDANT = [
    ("ix_record_people_record_id", "record_people"),
    ("ix_record_places_record_id", "record_places"),
    ("ix_record_items_record_id", "record_items"),
    ("ix_record_occasions_record_id", "record_occasions"),
    ("ix_occasion_people_occasion_id", "occasion_people"),
]
_TRGM = [
    ("ix_people_canonical_name_trgm", "people", "canonical_name"),
    ("ix_places_name_trgm", "places", "name"),
    ("ix_items_name_trgm", "items", "name"),
]


def upgrade() -> None:
    for col in ("people", "places", "items"):
        op.execute(f"ALTER TABLE {col} ALTER COLUMN aliases SET DEFAULT '{{}}'")
    for name, _tbl in _REDUNDANT:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for name, tbl, colname in _TRGM:
        op.execute(
            f"CREATE INDEX {name} ON {tbl} USING gin ({colname} gin_trgm_ops)"
        )


def downgrade() -> None:
    for name, _tbl, _c in _TRGM:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    for name, tbl in _REDUNDANT:
        op.execute(f"CREATE INDEX {name} ON {tbl} ({name.rsplit('_', 3)[-3]})")
    for col in ("people", "places", "items"):
        op.execute(f"ALTER TABLE {col} ALTER COLUMN aliases DROP DEFAULT")
```

Fix the `downgrade` recreate to name the real column explicitly rather than
parsing the index name — spell it out:
```python
    _RECREATE = {
        "ix_record_people_record_id": ("record_people", "record_id"),
        "ix_record_places_record_id": ("record_places", "record_id"),
        "ix_record_items_record_id": ("record_items", "record_id"),
        "ix_record_occasions_record_id": ("record_occasions", "record_id"),
        "ix_occasion_people_occasion_id": ("occasion_people", "occasion_id"),
    }
    for name, (tbl, colname) in _RECREATE.items():
        op.execute(f"CREATE INDEX {name} ON {tbl} ({colname})")
```

- [ ] **Step 4: Mirror the full index set onto the ORM** — `io_assistant/db/models.py`

Add `Index` to the import from `sqlalchemy`, and give each model a
`__table_args__` listing exactly the indexes the two migrations create. For
example:
```python
from sqlalchemy import (
    BigInteger, Date, DateTime, Float, ForeignKey, Index, String, Text, func,
)

class Person(Base):
    __tablename__ = "people"
    __table_args__ = (
        Index("ix_people_aliases", "aliases", postgresql_using="gin"),
        Index("ix_people_canonical_name_trgm", "canonical_name",
              postgresql_using="gin",
              postgresql_ops={"canonical_name": "gin_trgm_ops"}),
        Index("ix_people_embedding", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )
    ...
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list,
        server_default=text("'{}'"),
    )
```
Do the same for `Place`, `Item` (trgm on `name`), `Occasion` (embedding +
`ix_occasions_date`), `Record` (`ix_records_*` b-tree set + embedding),
`Utterance` (`ix_utterances_captured_at`), and each link table (only the
*second*-column index that survives). Import `text` from `sqlalchemy` for the
`server_default`. Match index names and column lists to `0001` + `0002`
exactly.

- [ ] **Step 5: Rebuild the test schema and run**

The `engine` fixture runs `alembic upgrade head`, so it will pick up `0002`.
Run: `uv run pytest tests/test_db_models.py -v`
Expected: PASS.
Also run the whole suite to confirm the dropped indexes / new default break
nothing: `uv run pytest -q` → PASS.

- [ ] **Step 6: (optional) autogenerate-clean check**

Run: `uv run alembic -c alembic.ini upgrade head && uv run alembic check`
Expected: "No new upgrade operations detected." If it reports index diffs,
reconcile the `__table_args__` names/ops with the migration until clean. Record
the outcome in the commit message.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/db/migrations/versions/0002_cleanup_and_trgm.py io_assistant/db/models.py tests/test_db_models.py
git commit -m "feat: migration 0002 (aliases default, drop redundant indexes, pg_trgm); declare indexes on ORM"
```

---

## Task 6: `EntityResolver` — honour aliases, narrow candidates in SQL

**Files:**
- Modify: `io_assistant/resolve/resolver.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: the `pg_trgm` indexes from Task 5; `ResolverConfig`
  (`fuzzy_threshold`, `vector_similarity_threshold`).
- Produces: `EntityResolver.resolve(entity_type, name, aliases)` unchanged
  signature and `ResolveOutcome` return, but:
  1. the caller-supplied `aliases` are considered in the exact-match step
     (an incoming alias that equals a stored canonical name — or vice versa —
     is a hit);
  2. the fuzzy step scores against stored `aliases[]` too, not only the name
     column;
  3. candidates are narrowed in SQL — exact/`ILIKE` on name or `aliases`,
     `UNION` a `similarity(name, :q) > 0.3` trigram match (uses
     `ix_*_name_trgm`), capped at 50 rows — instead of
     `SELECT id, name, aliases FROM <table>` with no `WHERE`. The vector step
     already runs in SQL and is unchanged.

**Background:** `resolve()` does `select(model.id, name_col, model.aliases)` with
no filter and fuzzy-scores every row in Python. It also ignores the `aliases`
argument entirely for matching, and `fuzz.token_set_ratio` only sees `cname`.
On a store of thousands of people this is O(n) Python per entity per utterance.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_resolve.py`

```python
@requires_db
def test_incoming_alias_matches_stored_canonical(db, config):
    from io_assistant.resolve.resolver import EntityResolver
    from io_assistant.db import models as m
    db.add(m.Person(canonical_name="Muhammad Nafay", aliases=[])); db.flush()
    r = EntityResolver(db, _ZeroEmbedder(), config.resolver)
    out = r.resolve("person", "Nafay Khan", ["Muhammad Nafay"])
    assert out.entity_id is not None and out.is_new is False

@requires_db
def test_fuzzy_matches_against_stored_alias(db, config):
    from io_assistant.resolve.resolver import EntityResolver
    from io_assistant.db import models as m
    db.add(m.Person(canonical_name="Eelian", aliases=["Eely"])); db.flush()
    r = EntityResolver(db, _ZeroEmbedder(), config.resolver)
    out = r.resolve("person", "Eeely", [])   # ~ alias, not canonical
    assert out.entity_id is not None

@requires_db
def test_resolve_does_not_full_scan(db, config, monkeypatch):
    """The Python-side loop must run over a bounded candidate set, not the
    whole table."""
    from io_assistant.resolve import resolver as rmod
    from io_assistant.db import models as m
    for i in range(60):
        db.add(m.Person(canonical_name=f"Person Number {i}", aliases=[]))
    db.flush()
    seen = {}
    real = rmod.EntityResolver._candidate_rows
    def spy(self, etype, name, aliases):
        rows = real(self, etype, name, aliases)
        seen["n"] = len(rows)
        return rows
    monkeypatch.setattr(rmod.EntityResolver, "_candidate_rows", spy)
    rmod.EntityResolver(db, _ZeroEmbedder(), config.resolver).resolve(
        "person", "Totally Unrelated Name", [])
    assert seen["n"] <= 50
```

Add a `_ZeroEmbedder` helper at the top of `tests/test_resolve.py` if one is not
already present:
```python
class _ZeroEmbedder:
    def embed_one(self, t): return [0.0] * 768
    def embed(self, ts): return [[0.0] * 768 for _ in ts]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_resolve.py -k "incoming_alias or stored_alias or full_scan" -v`
Expected: FAIL — first two return `is_new=True`; the third `AttributeError`
(no `_candidate_rows`).

- [ ] **Step 3: Implement** — rewrite the front half of `resolve()` in
  `io_assistant/resolve/resolver.py`

```python
from sqlalchemy import func, or_, select

    def _candidate_rows(self, entity_type, name, aliases):
        model, name_col = self._model_col(entity_type)
        needles = [name, *aliases]
        lowered = [n.lower() for n in needles]
        exact = select(model.id, name_col, model.aliases).where(
            or_(
                func.lower(name_col).in_(lowered),
                model.aliases.op("&&")(needles),  # array overlap
            )
        )
        trgm = (
            select(model.id, name_col, model.aliases)
            .where(func.similarity(name_col, name) > 0.3)
            .order_by(func.similarity(name_col, name).desc())
            .limit(50)
        )
        rows = {}
        for cid, cname, caliases in self.session.execute(exact).all():
            rows[cid] = (cid, cname, caliases)
        for cid, cname, caliases in self.session.execute(trgm).all():
            rows.setdefault(cid, (cid, cname, caliases))
        return list(rows.values())

    def resolve(self, entity_type, name, aliases):
        model, name_col = self._model_col(entity_type)
        lowered = name.lower()
        incoming_aliases = {a.lower() for a in aliases}
        rows = self._candidate_rows(entity_type, name, aliases)

        # 1. exact: incoming name/alias vs stored name/alias, case-insensitive
        for cid, cname, caliases in rows:
            stored = {cname.lower(), *[a.lower() for a in (caliases or [])]}
            if lowered in stored or stored & incoming_aliases or cname.lower() in incoming_aliases:
                return ResolveOutcome(cid, False, False, None, None)

        # 2. fuzzy: best token_set_ratio over name AND stored aliases
        best_id, best_score = None, -1.0
        for cid, cname, caliases in rows:
            candidates = [cname, *(caliases or [])]
            score = max(fuzz.token_set_ratio(name, c) for c in candidates)
            if score > best_score:
                best_score, best_id = score, cid
        if best_id is not None and best_score >= self.cfg.fuzzy_threshold:
            return ResolveOutcome(best_id, False, False, None, None)
```
Leave steps 3 (vector) and 4 (none) exactly as they are.

- [ ] **Step 4: Run the resolver suite**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: PASS — the new tests and every existing seeded-matrix case. If an
existing case regresses because trigram `> 0.3` excludes a candidate the old
full scan reached, lower the threshold to `0.2` (still index-backed) rather
than removing the narrowing.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/resolve/resolver.py tests/test_resolve.py
git commit -m "perf/fix: EntityResolver narrows candidates in SQL and honours aliases"
```

---

## Task 7: `persist_store` minors — referenced-name resolution, recurrence gate, items-link test

**Files:**
- Modify: `io_assistant/persist/writer.py`
- Test: `tests/test_persist.py`

**Interfaces:**
- Consumes: `resolver` (same object), `ground` / `to_rrule`
  (`io_assistant.resolve.dates`).
- Produces: `persist_store` behaviour changes:
  1. **Referenced names are resolved even when absent from the top-level
     lists.** Any `rec.assigned_by`, `rec.people[]`, `rec.places[]`,
     `rec.items[]`, `rec.occasions[]` value that has no `(etype, lower(name))`
     entry after the top-level pass gets its own `resolver.resolve(...)` /
     create, instead of being silently dropped from the links.
  2. **Unparseable `recurrence_phrase` gates.** If `rec.recurrence_phrase` is
     non-empty and `to_rrule()` returns `None`, add a gate reason
     `f"couldn't read the repeat rule '{rec.recurrence_phrase}'"` (same
     `confirmed` bypass as the date gate).
  3. No behaviour change for the happy path; `PersistResult` shape unchanged.

**Background (from the Plan 1 review ledger):**
- `_write` builds `entity_ids` only from `outcomes`, which is populated only
  from `extraction.people/places/items`. A record that names a person only
  inside `rec.people` (the extractor sometimes does this) links nothing.
- `to_rrule()` failure is swallowed: the record persists with
  `recurrence_rule = NULL` and the user is never told the "every other Tuesday"
  they said was dropped.
- The `RecordItem` link path has no test at all.

- [ ] **Step 1: Write the failing tests** — add to `tests/test_persist.py`

```python
@requires_db
def test_record_only_person_still_links(db, config):
    from io_assistant.persist.writer import persist_store
    from io_assistant.resolve.resolver import EntityResolver
    from io_assistant.models_domain import ExtractionResult, ExtractedRecord
    from io_assistant.db import models as m
    import datetime as dt
    now = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)
    emb = _ZeroEmbedder()
    ext = ExtractionResult(records=[ExtractedRecord(
        kind="event", title="lunch", when_phrase="today",
        people=["Sana"], confidence=0.9,          # NOT in top-level people[]
    )])
    res = persist_store(db, emb, EntityResolver(db, emb, config.resolver),
                        utterance_text="lunch with Sana", source="text",
                        captured_at=now, extraction=ext, now=now,
                        confidence_gate=0.6)
    rid = res.record_ids[0]
    assert db.query(m.RecordPerson).filter_by(record_id=rid).count() == 1

@requires_db
def test_record_item_link_persists(db, config):
    from io_assistant.persist.writer import persist_store
    from io_assistant.resolve.resolver import EntityResolver
    from io_assistant.models_domain import (
        ExtractionResult, ExtractedRecord, ExtractedItem)
    from io_assistant.db import models as m
    import datetime as dt
    now = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)
    emb = _ZeroEmbedder()
    ext = ExtractionResult(
        items=[ExtractedItem(name="drill", aliases=[], confidence=0.9)],
        records=[ExtractedRecord(kind="task", title="return the drill",
                                 items=["drill"], confidence=0.9)],
    )
    res = persist_store(db, emb, EntityResolver(db, emb, config.resolver),
                        utterance_text="return the drill", source="text",
                        captured_at=now, extraction=ext, now=now,
                        confidence_gate=0.6)
    rid = res.record_ids[0]
    assert db.query(m.RecordItem).filter_by(record_id=rid).count() == 1

@requires_db
def test_unreadable_recurrence_gates(db, config):
    from io_assistant.persist.writer import persist_store
    from io_assistant.resolve.resolver import EntityResolver
    from io_assistant.models_domain import ExtractionResult, ExtractedRecord
    import datetime as dt
    now = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)
    emb = _ZeroEmbedder()
    ext = ExtractionResult(records=[ExtractedRecord(
        kind="chore", title="water plants",
        recurrence_phrase="whenever the soil looks dry", confidence=0.9,
    )])
    res = persist_store(db, emb, EntityResolver(db, emb, config.resolver),
                        utterance_text="water the plants when dry", source="text",
                        captured_at=now, extraction=ext, now=now,
                        confidence_gate=0.6)
    assert res.gated is True
    assert any("repeat rule" in r for r in res.gate_reasons)
```

Add the `_ZeroEmbedder` helper to `tests/test_persist.py` if absent (same shape
as Task 6).

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_persist.py -k "only_person_still_links or record_item_link or unreadable_recurrence" -v`
Expected: FAIL — no `RecordPerson` row; (item test may already pass — if so keep
it as a regression guard); no gate reason for the recurrence phrase.

- [ ] **Step 3: Implement — recurrence gate** in `persist_store` (`writer.py`)

In the `for rec in extraction.records:` gate loop, after the date-phrase check:
```python
        if rec.recurrence_phrase and to_rrule(rec.recurrence_phrase) is None:
            gate_reasons.append(
                f"couldn't read the repeat rule '{rec.recurrence_phrase}'"
            )
```

- [ ] **Step 4: Implement — resolve referenced names** in `_write` (`writer.py`)

Add a helper inside `_write`, right after the top-level `for key, outcome in
outcomes.items():` block that fills `entity_ids`:
```python
    def _ensure(etype: str, raw_name: str) -> int | None:
        key = (etype, raw_name.lower())
        if key in entity_ids:
            return entity_ids[key]
        outcome = resolver.resolve(etype, raw_name, [])
        if outcome.entity_id is not None:
            entity_ids[key] = outcome.entity_id
        elif getattr(outcome, "ambiguous", False):
            entity_ids[key] = outcome.candidate_id
        else:
            entity_ids[key] = resolver.create(etype, raw_name, [])
            new_entities.append((etype, raw_name))
        return entity_ids[key]
```
Then in the per-record link loop, replace the `.get(...)` lookups with
`_ensure(...)`:
```python
        if rec.assigned_by:
            assigned_by_id = _ensure("person", rec.assigned_by)
        ...
        for pname in rec.people:
            pid = _ensure("person", pname)
            if pid is not None:
                session.add(m.RecordPerson(record_id=row.id, person_id=pid))
        for plname in rec.places:
            plid = _ensure("place", plname)
            if plid is not None:
                session.add(m.RecordPlace(record_id=row.id, place_id=plid))
        for iname in rec.items:
            iid = _ensure("item", iname)
            if iid is not None:
                session.add(m.RecordItem(record_id=row.id, item_id=iid))
```
`assigned_by_id` is computed before `row` is built (as today) — hoist the
`_ensure("person", rec.assigned_by)` call to where `assigned_by_id` is set,
before `m.Record(...)`. Occasions stay on the existing `occasion_ids` path
(they are not resolver entities).

Note: a name that *was* in the top-level list and hit the gate as `ambiguous`
is still gated before `_write` runs, so `_ensure` only ever sees confirmed or
ungated extractions — matching the existing ambiguity-accept behaviour.

- [ ] **Step 5: Run the persist suite**

Run: `uv run pytest tests/test_persist.py -v`
Expected: PASS — new tests plus every existing case (the dedup-by-key and
confirm-accepts-candidate tests still hold because `_ensure` reuses
`entity_ids`).

- [ ] **Step 6: Commit**

```bash
git add io_assistant/persist/writer.py tests/test_persist.py
git commit -m "fix: persist_store resolves record-referenced names and gates unreadable recurrence"
```

---

## Self-Review

**Spec coverage:**
- §3 indexing / "embedding dimension is fixed" → Task 1 (guard), Task 5
  (indexes declared on ORM, redundant ones dropped).
- §4.2 resolve order (exact → fuzzy → vector → new) → Task 6 preserves the
  order; adds alias handling the spec's resolver description implies.
- §4.3 confirmation gate → Task 7 extends the gate to unreadable recurrence,
  consistent with the existing date gate.
- §4.5 persist "resolve every referenced entity" → Task 7 stops dropping names
  that appear only inside a record.
- Connection lifecycle for the Plan 3 service → Task 4.

Not in this plan (still in `backlog.md`, deferred to Plan 2 or later): extraction
eval held-out set; ISO/absolute date-string grounding; router quality on the
light profile; occasion dedupe scoping + alias/notes enrichment on resolve-hit;
gate-message "about to store" summary; `io repl` per-line exception recovery.
These are not entangled with the query pipeline and are safe to carry forward.

**Placeholder scan:** none — every step has literal code or an exact command.

**Type consistency:**
- `ResolveOutcome` fields (`entity_id`, `is_new`, `ambiguous`, `candidate_id`,
  `candidate_name`) used identically in Tasks 6 and 7.
- `PersistResult` shape unchanged across Task 4 and Task 7.
- `session_factory` is `Callable[[], Session]` in Task 4; `cli.py` and the
  `conn_factory` fixture both supply that.
- Migration `revision`/`down_revision` chain: `0001` → `0002` (Task 5).
- `_candidate_rows` is the method name spied on in the Task 6 test and defined
  in the Task 6 implementation.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task, review between
   tasks. Tasks 3 and 4 are sequential (4 depends on 3's fixture); 1, 2, 5 are
   independent; 6 depends on 5's trigram index; 7 depends on 3.
2. **Inline Execution** — `superpowers:executing-plans`, batched with review
   checkpoints.
