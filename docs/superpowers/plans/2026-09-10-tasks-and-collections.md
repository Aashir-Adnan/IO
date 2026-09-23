# Tasks & Collections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user close a task by voice/text or a checkbox, have bare "I need to X" tasks default to due-today and keep surfacing until done, and let IO learn ad-hoc lists ("movies to watch") so they stay reliably findable however the user phrases the question.

**Architecture:** Five sequential phases on `io-window-glass`. A deterministic `close_record` (lexical match over open status-kind records; no model call) is reached from an orchestrator regex precheck *and* a `complete_record` capability, both routing through one `set_record_status` mutation. A read-time roll-forward rule in `compile_structured` makes overdue open tasks always in-window. A `collections` table (migration 0009) stores model-proposed list descriptors keyed by `kind` slug; `describe_collections()` is injected into the plan/decide prompts so routing reuses slugs. The LLM only identifies completion intent + a search phrase, and proposes a list's name/synonyms — Python owns identity, SQL, dates, ranking.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x + Alembic, FastAPI, pydantic v2, `rapidfuzz` (already a dep), pgvector, vanilla-JS frontend (no build). `uv run` for everything.

**Spec:** `docs/superpowers/specs/2026-09-10-tasks-and-collections-design.md` (read alongside this plan).

## Global Constraints

- **LLM boundary** (`.claude/rules/llm-boundaries.md`): model is called only for route/extract/plan/phrase/decide. In this feature it may *identify* a completion and emit a search phrase, and *propose* a collection descriptor. It must never emit SQL, pick a record id, write a `status`, do date arithmetic, filter, or rank. All of that is Python.
- **Migrations** (`.claude/rules/migrations.md`): Alembic only, no ad-hoc ALTER. `embedding_dim` stays `768`. New revisions chain from head `0007`: `0008_task_completion`, then `0009_collections`.
- **Test discipline** (`.claude/rules/test-discipline.md`): TDD — failing test first, watch it fail, minimal code, watch it pass, commit. Never mock the database; tests run against real PostgreSQL named by `IO_TEST_DATABASE_URL`. Model calls use the `FakeBackend` double (`tests/conftest.py`); embeddings use `StubEmbedder`. Service/CLI tests that commit through their own engine must clean the tables they touch.
- **local-first** (`.claude/rules/local-first.md`): no new outbound traffic. This feature opens no sockets. `tests/test_e2e_store.py`'s socket guard stays green.
- **Package** is `io_assistant` (never `io`). CLI command is `io`. Run tests: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run pytest -q`.
- **No config keys added.** The feature is always on; `provider="local"` behaviour is identical (extra prompt context is small; close/registry paths are pure Python).
- **Frontend**: no new vendored assets. Reuse existing Phosphor paths in `frontend/vendor/icons.js` (`checkCircle`, `circle` already exist).
- Deselect the known-flaky `tests/test_service_standby.py::test_standby_panel` when running the full suite (`--deselect`), as prior sessions have.

## File Structure

**New:**

| file | responsibility |
|---|---|
| `io_assistant/db/migrations/versions/0008_task_completion.py` | `records.completed_at TIMESTAMPTZ NULL` |
| `io_assistant/db/migrations/versions/0009_collections.py` | `collections` table |
| `io_assistant/tasks/__init__.py` | package marker |
| `io_assistant/tasks/complete.py` | `CloseOutcome`, `close_record()`, `set_record_status()` — deterministic, no model |
| `io_assistant/collections/__init__.py` | package marker |
| `io_assistant/collections/registry.py` | `upsert_collection()`, `describe_collections()`, `resolve_collection()`, `checkable_kinds()` |
| `tests/test_tasks_complete.py` | `close_record` / `set_record_status` |
| `tests/test_orchestrator_tasks.py` | precheck, capability, gate round-trip, no-duplicate |
| `tests/test_collections_registry.py` | upsert/merge/resolve/describe |

**Modified:**

| file | change |
|---|---|
| `io_assistant/models_domain.py` | `_KIND_ALIASES` in `normalize_kind`; `ExtractedCollection` model + `ExtractedRecord.collection`; `CollectionCard` |
| `io_assistant/db/models.py` | `Record.completed_at`; `Collection` ORM model |
| `io_assistant/persist/writer.py` | default-today for bare tasks; `_is_someday`; `upsert_collection` call; `status="open"` for checkable-collection kinds |
| `io_assistant/orchestrator.py` | `_complete_precheck`, `_try_complete`, `_resolve_completion`, `PendingComplete`, `_action_complete_record`; pending-branch dispatch by type |
| `io_assistant/actions/registry.py` | `complete_record` capability |
| `io_assistant/query/compile.py` | roll-forward OR-clause; `aggregation == "count"` branch |
| `io_assistant/query/plan.py` | (none — `status_filter` already parsed) |
| `io_assistant/query/pipeline.py` | pass collection vocabulary into planner context; open/done split for collection answers |
| `io_assistant/query/respond.py` | `overdue` + `due_label` per row in `rows_to_json` |
| `io_assistant/query/rank.py` | overdue open-task score bump |
| `io_assistant/orchestrator_cards.py` | widen `TaskListCard`; emit `CollectionCard` |
| `io_assistant/prompts/plan.txt` | "Known lists" rule; tasks → `status_filter:["open"]`, null window |
| `io_assistant/prompts/decide.txt` | reuse registered slugs |
| `io_assistant/extract/schema.py` | `collection` key in `SCHEMA_JSON`; one few-shot |
| `io_assistant/service/app.py` | `record_edit` maintains `completed_at`; `_run` passes reply text to a completion gate; `app.state.pending` type |
| `io_assistant/backend/anthropic_backend.py` / `local.py` | `plan()` prepends the vocabulary preamble (via `context`) — no signature change |
| `io_assistant/cli.py` | `io list` (Phase 5) |
| `frontend/components/card.js` | interactive `tasklist` checkbox; `collection` card |
| `frontend/views/records.js` | status check button; collection filter chips |
| `frontend/app.css` | `.task-check`, `.task-t.done`, `.record-title.done`, `.card-collection` |
| `frontend/api.js` | (none — `editRecord` covers status) |
| `.claude/knowledge/tasks-and-collections.md` | new knowledge doc (Task 26) |
| `.claude/knowledge/query-pipeline.md`, `data-model.md` | roll-forward, `completed_at`, `collections` |

---

# Phase 1 — Task completion

Ships: a task can be marked done by chat or checkbox; no duplicate records; ambiguity asks which one.

---

### Task 1: Kind aliases (todo/reminder → task)

**Files:**
- Modify: `io_assistant/models_domain.py` (`normalize_kind`, ~line 190)
- Test: `tests/test_models_domain.py` (create if absent)

**Interfaces:**
- Produces: `normalize_kind(raw: str) -> str` — unchanged signature; now maps `todo`, `to_do`, `to-do`, `reminder`, `reminders`, `task_reminder` → `task`; `chores` → `chore`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_domain.py
from io_assistant.models_domain import normalize_kind


def test_normalize_kind_slugifies():
    assert normalize_kind("Gym Session") == "gym_session"
    assert normalize_kind("  ") == "note"


def test_normalize_kind_aliases_todo_and_reminder_to_task():
    for raw in ("todo", "to-do", "to do", "reminder", "Reminders", "TASK_REMINDER"):
        assert normalize_kind(raw) == "task"
    assert normalize_kind("chores") == "chore"
    assert normalize_kind("watchlist") == "watchlist"  # unknown slug untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models_domain.py -q`
Expected: FAIL on the alias test (`'todo' == 'task'` assertion).

- [ ] **Step 3: Implement**

In `io_assistant/models_domain.py`, add above `normalize_kind`:

```python
_KIND_ALIASES = {
    "todo": "task", "to_do": "task", "task_reminder": "task",
    "reminder": "task", "reminders": "task",
    "chores": "chore",
}
```

At the end of `normalize_kind`, before `return s or "note"`:

```python
    s = _KIND_ALIASES.get(s, s)
    return s or "note"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_models_domain.py -q`
Expected: PASS (both tests).

- [ ] **Step 5: Run the writer tests (nothing regressed)**

Run: `uv run pytest tests/test_persist_writer.py tests/test_query_plan.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/models_domain.py tests/test_models_domain.py
git commit -m "feat(tasks): normalize todo/reminder kinds to 'task'"
```

---

### Task 2: Migration 0008 — `records.completed_at`

**Files:**
- Create: `io_assistant/db/migrations/versions/0008_task_completion.py`
- Modify: `io_assistant/db/models.py` (`Record`, ~line 113)
- Test: `tests/test_migrations.py` (append; or create)

**Interfaces:**
- Produces: `Record.completed_at: Mapped[datetime | None]` (column `completed_at`, `TIMESTAMPTZ NULL`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrations.py  (append)
def test_records_has_completed_at(engine):
    from sqlalchemy import inspect
    cols = {c["name"] for c in inspect(engine).get_columns("records")}
    assert "completed_at" in cols
```

(The `engine` fixture in `tests/conftest.py` runs `alembic upgrade head` against `io_test`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migrations.py::test_records_has_completed_at -q`
Expected: FAIL — `completed_at` not in columns.

- [ ] **Step 3: Write the migration**

```python
# io_assistant/db/migrations/versions/0008_task_completion.py
"""records.completed_at: set when a task/list item is marked done

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "records",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("records", "completed_at")
```

- [ ] **Step 4: Add the ORM column**

In `io_assistant/db/models.py`, in `class Record`, right after the `status` column (~line 113):

```python
    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
```

- [ ] **Step 5: Run the migration + test**

Run: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run pytest tests/test_migrations.py -q`
Expected: PASS. (conftest re-runs `upgrade head` per session.)

- [ ] **Step 6: Verify down-migration**

Run:
```bash
IO_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run alembic downgrade 0007
IO_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run alembic upgrade head
```
Expected: both succeed, no error.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/db/migrations/versions/0008_task_completion.py io_assistant/db/models.py tests/test_migrations.py
git commit -m "feat(tasks): migration 0008 — records.completed_at"
```

---

### Task 3: `set_record_status` — the single mutation point

**Files:**
- Create: `io_assistant/tasks/__init__.py` (empty)
- Create: `io_assistant/tasks/complete.py`
- Test: `tests/test_tasks_complete.py`

**Interfaces:**
- Produces:
  - `set_record_status(session, record: m.Record, status: str, now: datetime) -> None` — sets `record.status`; when `status == "done"` and `record.completed_at is None` sets `completed_at = now`; when `status == "open"` sets `completed_at = None`. No commit (caller owns the transaction).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tasks_complete.py
import datetime as dt

from io_assistant.db import models as m
from io_assistant.tasks.complete import set_record_status
from tests.conftest import requires_db

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


@requires_db
def test_set_record_status_done_stamps_completed_at(db):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    r = m.Record(kind="task", title="buy milk", status="open",
                 source_utterance_id=u.id)
    db.add(r); db.flush()

    set_record_status(db, r, "done", NOW)
    assert r.status == "done" and r.completed_at == NOW

    set_record_status(db, r, "open", NOW)
    assert r.status == "open" and r.completed_at is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tasks_complete.py -q`
Expected: FAIL — `ModuleNotFoundError: io_assistant.tasks`.

- [ ] **Step 3: Implement**

```python
# io_assistant/tasks/__init__.py
```

```python
# io_assistant/tasks/complete.py
from __future__ import annotations

from datetime import datetime

from io_assistant.db import models as m

__all__ = ["set_record_status"]


def set_record_status(session, record: m.Record, status: str, now: datetime) -> None:
    """The one place a record's task status changes. `done` stamps
    completed_at (once); `open` clears it. Caller owns the commit."""
    record.status = status
    if status == "done" and record.completed_at is None:
        record.completed_at = now
    elif status == "open":
        record.completed_at = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run pytest tests/test_tasks_complete.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/tasks/ tests/test_tasks_complete.py
git commit -m "feat(tasks): set_record_status — single status mutation point"
```

---

### Task 4: `close_record` — lexical match over open tasks

**Files:**
- Modify: `io_assistant/tasks/complete.py`
- Test: `tests/test_tasks_complete.py`

**Interfaces:**
- Consumes: `set_record_status` (Task 3), `m.Record`.
- Produces:
  - `@dataclass CloseOutcome: status: Literal["matched", "ambiguous", "none"]; record: m.Record | None; candidates: list[m.Record]`
  - `close_record(session, phrase: str, now: datetime, *, checkable_kinds: set[str], target_status: str = "done") -> CloseOutcome` — reads open records whose `kind` is in `checkable_kinds`, scores each by `rapidfuzz.fuzz.WRatio(phrase, title)`, returns `matched` (best ≥ 72 and clear of #2 by ≥ 12) with `.record` set, `ambiguous` (best ≥ 55, not clear) with up to 3 `.candidates`, else `none`. **Does not mutate.**
  - Phase 1 callers pass `checkable_kinds={"task", "chore"}`; Task 17 changes the call sites to add `checkable_kinds(session)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_tasks_complete.py  (append)
from io_assistant.tasks.complete import close_record, CloseOutcome

CK = {"task", "chore"}


def _task(db, title, status="open", kind="task"):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    r = m.Record(kind=kind, title=title, status=status, source_utterance_id=u.id)
    db.add(r); db.flush()
    return r


@requires_db
def test_close_record_matches_the_one_open_task(db):
    r = _task(db, "buy groceries for the week")
    out = close_record(db, "groceries", NOW, checkable_kinds=CK)
    assert out.status == "matched" and out.record.id == r.id


@requires_db
def test_close_record_ambiguous_when_two_plausible(db):
    _task(db, "call the dentist")
    _task(db, "book the dentist follow-up")
    out = close_record(db, "the dentist thing", NOW, checkable_kinds=CK)
    assert out.status == "ambiguous" and len(out.candidates) >= 2


@requires_db
def test_close_record_none_when_nothing_open_matches(db):
    _task(db, "buy groceries", status="done")
    _task(db, "renew passport")
    out = close_record(db, "the laundry", NOW, checkable_kinds=CK)
    assert out.status == "none"


@requires_db
def test_close_record_ignores_non_checkable_kinds(db):
    _task(db, "watched Dune", kind="watchlist")   # not in CK
    out = close_record(db, "Dune", NOW, checkable_kinds=CK)
    assert out.status == "none"
```

- [ ] **Step 2: Run to verify they fail**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_tasks_complete.py -q`
Expected: FAIL — `close_record` not defined.

- [ ] **Step 3: Implement**

```python
# io_assistant/tasks/complete.py  (add)
from dataclasses import dataclass, field
from typing import Literal

from rapidfuzz import fuzz
from sqlalchemy import select

_MATCH_FLOOR = 72.0
_AMBIG_FLOOR = 55.0
_CLEAR_MARGIN = 12.0


@dataclass
class CloseOutcome:
    status: Literal["matched", "ambiguous", "none"]
    record: m.Record | None = None
    candidates: list = field(default_factory=list)


def close_record(
    session,
    phrase: str,
    now: datetime,
    *,
    checkable_kinds: set[str],
    target_status: str = "done",
) -> CloseOutcome:
    if not phrase.strip() or not checkable_kinds:
        return CloseOutcome("none")
    rows = session.execute(
        select(m.Record).where(
            m.Record.status == "open",
            m.Record.kind.in_(sorted(checkable_kinds)),
        )
    ).scalars().all()
    if not rows:
        return CloseOutcome("none")
    scored = sorted(
        ((fuzz.WRatio(phrase, r.title), r) for r in rows),
        key=lambda t: t[0],
        reverse=True,
    )
    best_score, best = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= _MATCH_FLOOR and best_score - second >= _CLEAR_MARGIN:
        return CloseOutcome("matched", record=best)
    if best_score >= _AMBIG_FLOOR:
        return CloseOutcome(
            "ambiguous",
            candidates=[r for s, r in scored if s >= _AMBIG_FLOOR][:3],
        )
    return CloseOutcome("none")
```

(`target_status` is threaded now so a later `dropped` path reuses this; it does not affect scoring.)

- [ ] **Step 4: Run to verify they pass**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_tasks_complete.py -q`
Expected: PASS (all). If `test_close_record_ambiguous_when_two_plausible` is flaky on the margin, widen the two titles' shared tokens — do NOT loosen the constants.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/tasks/complete.py tests/test_tasks_complete.py
git commit -m "feat(tasks): close_record — lexical match over open status-kind records"
```

---

### Task 5: Orchestrator precheck + completion gate

**Files:**
- Modify: `io_assistant/orchestrator.py` (`PendingStore` area ~line 69; `_handle_in_session` ~line 155-210; add methods near `_web_precheck` ~line 414)
- Modify: `io_assistant/service/app.py` (`_run` ~line 76-95; `app.state.pending` type ~line 73)
- Test: `tests/test_orchestrator_tasks.py`

**Interfaces:**
- Consumes: `close_record`, `set_record_status`, `CloseOutcome` (Tasks 3-4); `HandleResult`, `PendingStore` (orchestrator).
- Produces:
  - `@dataclass PendingComplete: candidate_ids: list[int]; target_status: str` (a second pending payload alongside `PendingStore`).
  - `Orchestrator._complete_precheck(text: str) -> str | None` — returns `"done"`, `"dropped"`, or `None`.
  - `Orchestrator._try_complete(session, text, now, *, source, captured_at) -> HandleResult | None` — runs `close_record`; `matched` → mutate + ack `HandleResult`; `ambiguous` → gate `HandleResult` with `pending=PendingComplete`; `none` → an ack-style "I don't see an open task like that" `HandleResult` (NOT `None`; falling through would create a duplicate).
  - `Orchestrator._resolve_completion(session, pending: PendingComplete, reply_text: str) -> HandleResult` — Python ordinal/fuzzy parse of `reply_text` against candidate titles; closes the pick or re-gates.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_orchestrator_tasks.py
import datetime as dt

import pytest

from io_assistant.db import models as m
from io_assistant.orchestrator import Orchestrator
from io_assistant.models_domain import (
    ExtractionResult, ExtractedRecord, Plan, Step,
)
from tests.conftest import requires_db

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def _stub_embedder(monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())


def _orch(config, db, fake_backend):
    return Orchestrator(config, session_factory=lambda: db, backend=fake_backend)


def _open_task(db, title):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    r = m.Record(kind="task", title=title, status="open", source_utterance_id=u.id)
    db.add(r); db.flush()
    return r


@requires_db
def test_finishing_a_task_closes_it_without_a_duplicate(config, db, fake_backend):
    r = _open_task(db, "submit the expense report")
    before = db.query(m.Record).count()

    res = _orch(config, db, fake_backend).handle(
        "I finished the expense report", captured_at=NOW)

    db.refresh(r)
    assert r.status == "done" and r.completed_at is not None
    assert db.query(m.Record).count() == before   # no new record
    assert res.intent_kind == "ack"
    assert "plan" not in fake_backend.calls and "decide" not in fake_backend.calls


@requires_db
def test_i_need_to_still_stores_a_new_open_task(config, db, fake_backend):
    fake_backend.set_decide(Plan(steps=[Step(kind="store", extraction=ExtractionResult(
        records=[ExtractedRecord(kind="task", title="buy groceries",
                                 status="open", confidence=0.9)]))]))
    res = _orch(config, db, fake_backend).handle("I need to buy groceries", captured_at=NOW)
    assert db.query(m.Record).filter_by(title="buy groceries", status="open").count() == 1


@requires_db
def test_ambiguous_completion_gates_then_reply_closes_the_pick(config, db, fake_backend):
    a = _open_task(db, "call the dentist")
    b = _open_task(db, "book the dentist follow-up")
    o = _orch(config, db, fake_backend)

    gate = o.handle("mark the dentist thing done", captured_at=NOW)
    assert gate.intent_kind == "gate" and gate.pending is not None

    reply = o.handle("the first one", captured_at=NOW, pending=gate.pending)
    db.refresh(a); db.refresh(b)
    assert a.status == "done" and b.status == "open"
```

- [ ] **Step 2: Run to verify they fail**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_orchestrator_tasks.py -q`
Expected: FAIL — completion not wired; "I finished…" currently routes to `decide`/`store`.

- [ ] **Step 3: Implement — `PendingComplete` + precheck constants**

In `io_assistant/orchestrator.py`, after the `PendingStore` dataclass (~line 78):

```python
@dataclass
class PendingComplete:
    """A completion that needs the user to pick which open task they mean."""

    candidate_ids: list[int]
    target_status: str  # "done" | "dropped"
```

Near the top-level regexes (`_WEB_*`), add:

```python
import re as _re

_COMPLETE_DONE = _re.compile(
    r"^\s*(i(?:'ve| have)?\s+)?(finished|completed|did|wrapped up|took care of|"
    r"knocked out|handled)\b|"
    r"^\s*(mark|set|check|tick|cross)\b.*\b(done|complete|completed|off)\b|"
    r"^\s*(that'?s|it'?s)\s+(done|finished|handled)\b",
    _re.IGNORECASE,
)
_COMPLETE_DROP = _re.compile(
    r"^\s*(cancel|drop|forget|scrap|never ?mind)\b.*\b(task|reminder|"
    r"the .+)\b|^\s*(don'?t need to|not doing)\b",
    _re.IGNORECASE,
)
_COMPLETE_QUESTION = _re.compile(
    r"^\s*(did|have|has|is|are|was|were|do|does|can|could|will|would|should|when|"
    r"what|why|how)\b|\?\s*$",
    _re.IGNORECASE,
)
_COMPLETE_STRIP = _re.compile(
    r"^\s*(i(?:'ve| have)?\s+)?(finished|completed|did|wrapped up|took care of|"
    r"knocked out|handled|mark|set|check off|tick off|cross off|checked off)\s+",
    _re.IGNORECASE,
)
```

- [ ] **Step 4: Implement — the methods**

Add to `class Orchestrator`, next to `_web_precheck`:

```python
    def _complete_precheck(self, text: str) -> str | None:
        t = (text or "").strip()
        if not t or _COMPLETE_QUESTION.match(t):
            return None
        if _COMPLETE_DONE.match(t):
            return "done"
        if _COMPLETE_DROP.match(t):
            return "dropped"
        return None

    def _checkable_kinds(self, session) -> set[str]:
        kinds = {"task", "chore"}
        # Task 17 adds: kinds |= checkable_kinds(session)
        return kinds

    def _try_complete(self, session, text, now, *, source, captured_at):
        from io_assistant.tasks.complete import close_record, set_record_status

        target = self._complete_precheck(text) or "done"
        phrase = _COMPLETE_STRIP.sub("", text).strip(" .!").strip() or text
        session.add(m.Utterance(text=text, source=source, captured_at=captured_at,
                                resolved_intent="store", marker="complete"))
        session.flush()
        out = close_record(session, phrase, now,
                           checkable_kinds=self._checkable_kinds(session),
                           target_status=target)
        if out.status == "matched":
            set_record_status(session, out.record, target, now)
            verb = "Marked done" if target == "done" else "Dropped"
            return HandleResult("store", None, f"{verb}: {out.record.title}.",
                                intent_kind="ack",
                                cards=[_status_card(out.record)])
        if out.status == "ambiguous":
            lines = "\n".join(f"{i+1}. {r.title}" for i, r in enumerate(out.candidates))
            return HandleResult(
                "store", None,
                f"Which one do you mean?\n{lines}",
                intent_kind="gate",
                pending=PendingComplete(
                    candidate_ids=[r.id for r in out.candidates],
                    target_status=target,
                ),
            )
        return HandleResult("store", None,
                            "I don't see an open task like that.",
                            intent_kind="ack")

    def _resolve_completion(self, session, pending: "PendingComplete", reply_text: str):
        from io_assistant.tasks.complete import set_record_status

        rows = [session.get(m.Record, i) for i in pending.candidate_ids]
        rows = [r for r in rows if r is not None]
        pick = _pick_candidate(reply_text, rows)
        if pick is None:
            lines = "\n".join(f"{i+1}. {r.title}" for i, r in enumerate(rows))
            return HandleResult("store", None,
                                f"Still not sure — which one?\n{lines}",
                                intent_kind="gate", pending=pending)
        set_record_status(session, pick, pending.target_status, session_now(session))
        verb = "Marked done" if pending.target_status == "done" else "Dropped"
        return HandleResult("store", None, f"{verb}: {pick.title}.",
                            intent_kind="ack", cards=[_status_card(pick)])
```

Add module-level helpers in `orchestrator.py`:

```python
def _pick_candidate(reply: str, rows: list) -> "m.Record | None":
    from rapidfuzz import fuzz
    t = (reply or "").strip().lower()
    words = {"first": 1, "second": 2, "third": 3, "1st": 1, "2nd": 2, "3rd": 3,
             "one": 1, "two": 2, "three": 3, "1": 1, "2": 2, "3": 3, "a": 1, "b": 2}
    for w, n in words.items():
        if _re.search(rf"\b{_re.escape(w)}\b", t) and 1 <= n <= len(rows):
            return rows[n - 1]
    scored = sorted(((fuzz.WRatio(t, r.title), r) for r in rows),
                    key=lambda x: x[0], reverse=True)
    if scored and scored[0][0] >= 60:
        return scored[0][1]
    return None


def session_now(session) -> datetime:
    return datetime.now(timezone.utc)
```

(`session_now` is a tiny seam so a future test can freeze it; keep it trivial for now.)

`_status_card` — reuse the store card builder:

```python
def _status_card(record) -> "object":
    from io_assistant.models_domain import RecordCard
    return RecordCard(record_id=record.id, kind=record.kind, domain=record.domain,
                      title=record.title, when=record.occurred_at,
                      due=record.due_at, status=record.status)
```

- [ ] **Step 5: Implement — wire into `_handle_in_session` and the service**

In `_handle_in_session` (~line 168), replace the store-only pending branch:

```python
        if pending is not None:
            if isinstance(pending, PendingComplete):
                return self._resolve_completion(session, pending, text)
            # Replay of a gated store …
            return self._store(session, text=pending.text, …)   # unchanged
```

Right after `_emit("Understanding what you said")` (~line 183), before the web precheck:

```python
        if not confirmed and self._complete_precheck(text):
            done = self._try_complete(session, text, now,
                                      source=source, captured_at=captured_at)
            if done is not None:
                return done
```

Export the new name: add `"PendingComplete"` to `__all__`.

In `io_assistant/service/app.py`:
- `app.state.pending: dict[str, PendingStore | PendingComplete] = {}` and import `PendingComplete`.
- In `_run`, the call for a pending turn (~line 89-90) — pass the reply text so a completion gate can read it:

```python
        if pending is not None:
            result = orchestrator.handle(
                body.text or pending.text if hasattr(pending, "text") else body.text,
                pending=pending, source=..., captured_at=..., history=...,
            )
```

Simpler and correct: `text_arg = body.text or getattr(pending, "text", "")` computed once, passed as the first arg. The store replay ignores it (`_handle_in_session` uses `pending.text`), the completion replay uses it.

- [ ] **Step 6: Run the tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_orchestrator_tasks.py tests/test_orchestrator.py tests/test_service_ws.py -q`
Expected: PASS. Watch that `test_i_need_to_still_stores_a_new_open_task` proves the precheck's question/negation guard doesn't eat "I need to".

- [ ] **Step 7: Commit**

```bash
git add io_assistant/orchestrator.py io_assistant/service/app.py tests/test_orchestrator_tasks.py
git commit -m "feat(tasks): conversational completion — precheck, deterministic close, which-one gate"
```

---

### Task 6: `complete_record` capability (combined decide path)

**Files:**
- Modify: `io_assistant/actions/registry.py` (`REGISTRY`)
- Modify: `io_assistant/orchestrator.py` (`_action_handlers` ~line 319; add `_action_complete_record`)
- Test: `tests/test_orchestrator_tasks.py`, `tests/test_actions_registry.py`

**Interfaces:**
- Consumes: `_try_complete` (Task 5), `validate_action`.
- Produces: `REGISTRY["complete_record"]` with `args={"what": "..."}`; handler `_action_complete_record(session, args, *, text, now, **_)` delegating to `_try_complete` using `args["what"]` as the phrase (falling back to `text`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator_tasks.py  (append)
@requires_db
def test_decide_complete_record_action_closes_the_task(config, db, fake_backend):
    r = _open_task(db, "water the plants")
    fake_backend.set_decide(Plan(steps=[
        Step(kind="action", action="complete_record", args={"what": "the plants"})]))
    res = _orch(config, db, fake_backend).handle("crossed the plants off", captured_at=NOW)
    db.refresh(r)
    assert r.status == "done" and res.intent_kind == "ack"
```

```python
# tests/test_actions_registry.py  (append)
def test_complete_record_capability_registered():
    from io_assistant.actions.registry import REGISTRY, describe_capabilities
    assert "complete_record" in REGISTRY
    assert "what" in REGISTRY["complete_record"].args
    assert "complete_record" in describe_capabilities(files_enabled=False, web_enabled=False)
```

- [ ] **Step 2: Run to verify they fail**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_actions_registry.py::test_complete_record_capability_registered tests/test_orchestrator_tasks.py::test_decide_complete_record_action_closes_the_task -q`
Expected: FAIL.

- [ ] **Step 3: Implement — registry entry**

In `io_assistant/actions/registry.py`, add to `REGISTRY` (no `requires_*` — always available):

```python
    "complete_record": Capability(
        slug="complete_record",
        summary=("Mark an existing OPEN task or list item as done / dropped — "
                 "'I finished the report', 'cross milk off the list', 'cancel "
                 "the dentist reminder'. NOT for a task the user still needs to "
                 "do (that is a store step)."),
        args={"what": "string — the task or item being completed, as the user named it"},
    ),
```

- [ ] **Step 4: Implement — handler**

In `_action_handlers` (~line 320), add `"complete_record": self._action_complete_record,`. Then:

```python
    def _action_complete_record(self, session, args, *, text, source, captured_at,
                                now, history, **_):
        phrase = (args.get("what") or "").strip() or text
        res = self._try_complete(session, phrase, now,
                                 source=source, captured_at=captured_at)
        return res if res is not None else HandleResult(
            "store", None, "I don't see an open task like that.", intent_kind="ack")
```

Note `_try_complete` currently derives `target` from `_complete_precheck(text)`; when called from the action the text may not match the precheck, so default `"done"` applies — correct for `complete_record`. For a "cancel/drop" phrasing routed here, `_complete_precheck` on the raw text still returns `"dropped"`, so keep passing `text` (not `phrase`) into the precheck inside `_try_complete` — it already does.

- [ ] **Step 5: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_actions_registry.py tests/test_orchestrator_tasks.py tests/test_decide_combined.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/actions/registry.py io_assistant/orchestrator.py tests/test_actions_registry.py tests/test_orchestrator_tasks.py
git commit -m "feat(tasks): complete_record capability for the combined decide path"
```

---

### Task 7: `PATCH /record` maintains `completed_at`

**Files:**
- Modify: `io_assistant/service/app.py` (`record_edit`, ~line 273-307)
- Test: `tests/test_service_entity.py`

**Interfaces:**
- Consumes: `set_record_status` (Task 3).
- Produces: `PATCH /record/{id}` with `{"status": "done"}` → row `status="done"`, `completed_at` set; `{"status": "open"}` → `completed_at` cleared. `RecordEditIn` already has `status: str | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_service_entity.py  (append inside the existing test module style)
@requires_db
def test_patch_record_status_maintains_completed_at(config, fake_backend, db):
    u = m.Utterance(text="x", source="text", captured_at=NOW)
    db.add(u); db.flush()
    r = m.Record(kind="task", domain="home", title="mop the floor",
                 status="open", attributes={}, source_utterance_id=u.id)
    db.add(r); db.flush(); rid = r.id

    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        done = c.patch(f"/record/{rid}", json={"status": "done"}).json()
        assert done["status"] == "done"
        db.expire_all()
        assert db.get(m.Record, rid).completed_at is not None
        c.patch(f"/record/{rid}", json={"status": "open"})
        db.expire_all()
        assert db.get(m.Record, rid).completed_at is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_service_entity.py::test_patch_record_status_maintains_completed_at -q`
Expected: FAIL — `completed_at` stays `None` (endpoint sets `row.status` directly).

- [ ] **Step 3: Implement**

In `record_edit`, replace the `status` branch:

```python
            if body.status is not None:
                from io_assistant.tasks.complete import set_record_status
                import datetime as _dt
                set_record_status(s, row, body.status or "open",
                                  _dt.datetime.now(_dt.timezone.utc))
```

(When `body.status` is `""` treat as re-open. The existing `row.status = body.status or None` semantics change slightly — document in the knowledge doc that a cleared status means "open" for task-kinds.)

- [ ] **Step 4: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_service_entity.py -q`
Expected: PASS (including `test_records_browse_edit_delete`).

- [ ] **Step 5: Commit**

```bash
git add io_assistant/service/app.py tests/test_service_entity.py
git commit -m "feat(tasks): PATCH /record status flips completed_at via set_record_status"
```

---

### Task 8: Interactive checkbox — tasklist card + records browser

**Files:**
- Modify: `frontend/components/card.js` (`tasklist` branch, ~line 37-43)
- Modify: `frontend/views/records.js` (`rowEl`, ~line 60-90)
- Modify: `frontend/app.css`
- Test: `tests/test_frontend_smoke.py` or `tests/test_frontend_library.py` (whichever holds `node --check` + string assertions)

**Interfaces:**
- Consumes: `ctx.api.editRecord(id, patch)` (exists in `frontend/api.js`).
- Produces: clickable `.task-check` button per tasklist row and per status-bearing records-browser row; optimistic toggle, revert on error.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_frontend_library.py  (or _smoke)
def test_tasklist_card_has_interactive_checkbox():
    src = (FRONTEND / "components" / "card.js").read_text()
    assert "task-check" in src and "editRecord" in src

def test_records_row_has_status_toggle():
    src = (FRONTEND / "views" / "records.js").read_text()
    assert "record-check" in src
```

(Match the `FRONTEND` path constant already used in that test file.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_frontend_library.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement — card.js**

Replace the `tasklist` branch:

```javascript
  } else if (card.type === "tasklist") {
    el.innerHTML = `<div class="tasklist">${card.items.map((it) => `
      <div class="task-row" data-id="${it.record_id}">
        <button class="task-check" aria-pressed="${it.status === "done"}" aria-label="Toggle done">
          ${icon(it.status === "done" ? "checkCircle" : "circle", { size: 14, cls: "task-i" })}
        </button>
        <span class="task-t${it.status === "done" ? " done" : ""}">${escape(it.title)}</span>
        <span class="mono task-due">${it.due ? when(it.due).toUpperCase() : (it.status || "").toUpperCase()}</span>
      </div>`).join("")}</div>`;
    if (ctx) {
      el.querySelectorAll(".task-check").forEach((btn) => {
        btn.addEventListener("click", async () => {
          const row = btn.closest(".task-row");
          const id = +row.dataset.id;
          const next = btn.getAttribute("aria-pressed") === "true" ? "open" : "done";
          row.classList.toggle("done-row", next === "done");
          row.querySelector(".task-t").classList.toggle("done", next === "done");
          btn.setAttribute("aria-pressed", String(next === "done"));
          btn.innerHTML = icon(next === "done" ? "checkCircle" : "circle", { size: 14, cls: "task-i" });
          try { await ctx.api.editRecord(id, { status: next }); }
          catch {
            btn.setAttribute("aria-pressed", String(next !== "done"));
            btn.innerHTML = icon(next !== "done" ? "checkCircle" : "circle", { size: 14, cls: "task-i" });
            row.querySelector(".task-t").classList.toggle("done", next !== "done");
          }
        });
      });
    }
```

- [ ] **Step 4: Implement — records.js**

In `rowEl`, when `r.status` is set (task-kinds), prepend a check button before `.record-glyph`:

```javascript
    const checkable = r.status === "open" || r.status === "done";
    row.innerHTML = `
      ${checkable ? `<button class="record-check" aria-pressed="${r.status === "done"}" aria-label="Toggle done">${icon(r.status === "done" ? "checkCircle" : "circle", { size: 15 })}</button>` : ""}
      <span class="record-glyph">${icon(glyph, { size: 15 })}</span>
      ... (rest unchanged) ...`;
```

And after the title-blur handler:

```javascript
    const chk = row.querySelector(".record-check");
    if (chk) chk.addEventListener("click", async () => {
      const next = chk.getAttribute("aria-pressed") === "true" ? "open" : "done";
      chk.setAttribute("aria-pressed", String(next === "done"));
      chk.innerHTML = icon(next === "done" ? "checkCircle" : "circle", { size: 15 });
      row.querySelector(".record-title").classList.toggle("done", next === "done");
      try { const u = await ctx.api.editRecord(r.id, { status: next }); r.status = u.status; }
      catch {
        chk.setAttribute("aria-pressed", String(next !== "done"));
        chk.innerHTML = icon(next !== "done" ? "checkCircle" : "circle", { size: 15 });
        row.querySelector(".record-title").classList.toggle("done", next !== "done");
      }
    });
```

- [ ] **Step 5: Implement — app.css**

Add near the other `.task-*` rules:

```css
.task-check, .record-check {
  flex: none; width: 22px; height: 22px; display: grid; place-items: center;
  border-radius: 6px; color: var(--ink-3);
}
.task-check[aria-pressed="true"], .record-check[aria-pressed="true"] { color: var(--color-accent); }
.task-check:hover, .record-check:hover { color: var(--ink); background: var(--fill); }
.task-t.done, .record-title.done { text-decoration: line-through; color: var(--ink-3); }
```

- [ ] **Step 6: Run checks**

Run: `node --check frontend/components/card.js && node --check frontend/views/records.js && uv run pytest tests/test_frontend_library.py -q`
Expected: PASS + "JS OK".

- [ ] **Step 7: Commit**

```bash
git add frontend/components/card.js frontend/views/records.js frontend/app.css tests/test_frontend_library.py
git commit -m "feat(tasks): clickable check-off on the tasklist card and records browser"
```

---

### Task 9: Widen `TaskListCard` emission

**Files:**
- Modify: `io_assistant/orchestrator_cards.py` (`query_cards`, ~line 51-66)
- Test: `tests/test_orchestrator_cards.py` (create if absent) or `tests/test_query_pipeline.py`

**Interfaces:**
- Consumes: `QueryAnswer.list_records` (each a `RecordRef` with `.kind`, `.status`, `.due`).
- Produces: `query_cards` emits a `TaskListCard` when **any** row is a status-kind (`task`/`chore`, plus — after Task 17 — a checkable collection kind) OR has a due date; rows without a status still render via their own card path. Behaviour for pure event answers is unchanged (no tasklist).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator_cards.py
import datetime as dt
from io_assistant.orchestrator_cards import query_cards
from io_assistant.query.pipeline import QueryAnswer, RecordRef
from io_assistant.models_domain import TaskListCard
from tests.conftest import requires_db
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


@requires_db
def test_tasklist_card_emitted_for_open_task_without_due(db):
    ans = QueryAnswer(text="", shape="markdown", n_rows=1, source_record_ids=[],
        list_records=[RecordRef(record_id=1, kind="task", domain="home",
                                title="mop", status="open", when=None, due=None)])
    cards = query_cards(db, ans)
    assert any(isinstance(c, TaskListCard) for c in cards)


@requires_db
def test_no_tasklist_for_pure_event_answer(db):
    ans = QueryAnswer(text="", shape="text", n_rows=1, source_record_ids=[],
        list_records=[RecordRef(record_id=1, kind="event", domain="social",
                                title="dinner", status=None, when=NOW, due=None)])
    assert not any(isinstance(c, TaskListCard) for c in query_cards(db, ans))
```

- [ ] **Step 2: Run to verify it fails**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_orchestrator_cards.py -q`
Expected: FAIL — first test (the `all(...)` guard rejects a statusful row with no due).

- [ ] **Step 3: Implement**

```python
def query_cards(session, answer) -> list[Card]:
    cards: list[Card] = []
    if answer.source_record_ids:
        cards.append(SourcesCard(
            record_ids=list(answer.source_record_ids),
            count=len(answer.source_record_ids), labels=["memory"],
        ))
    lr = getattr(answer, "list_records", [])
    statusful = [r for r in lr if r.status in ("open", "done", "dropped") or r.due is not None]
    if statusful and len(statusful) >= max(1, len(lr) // 2):
        cards.append(TaskListCard(items=[
            TaskListItem(record_id=r.record_id, title=r.title, status=r.status, due=r.due)
            for r in statusful
        ]))
    return cards
```

- [ ] **Step 4: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_orchestrator_cards.py tests/test_query_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/orchestrator_cards.py tests/test_orchestrator_cards.py
git commit -m "feat(tasks): TaskListCard for open tasks without a due date"
```

**PHASE 1 CHECKPOINT** — run the full suite:
`IO_TEST_DATABASE_URL=... uv run pytest -q --deselect tests/test_service_standby.py::test_standby_panel`
All green (Ollama must be up for the two `test_orchestrator_files.py` tests). This is a natural merge point.

---

# Phase 2 — Default-today + roll-forward

Ships: a bare "I need to X" is due today; if still open tomorrow it shows as overdue in "what do I need to do" — no daily job.

---

### Task 10: Bare tasks default to due-today

**Files:**
- Modify: `io_assistant/persist/writer.py` (record loop, ~line 226-244; add `_is_someday`)
- Modify: `io_assistant/resolve/dates.py` (export `start_of_day` if not present)
- Test: `tests/test_persist_writer.py`

**Interfaces:**
- Consumes: `ground`, and a `start_of_day(now) -> datetime` helper (local midnight, tz from `now`).
- Produces: after this task, a `persist_store` of an `ExtractedRecord(kind="task")` with no `when_phrase`/`due_phrase`/`recurrence_phrase` and not "someday" → row `due_at == start_of_day(now)`. `event`/`gym_session`/etc are never touched. "someday/eventually/no rush/whenever/one day" phrasing → `due_at is None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_persist_writer.py  (append; match the module's existing fixtures)
def _persist_one(db, stub_embedder, resolver, rec, now):
    from io_assistant.persist.writer import persist_store
    from io_assistant.models_domain import ExtractionResult
    return persist_store(db, stub_embedder, resolver,
        utterance_text="x", source="text", captured_at=now,
        extraction=ExtractionResult(records=[rec]), now=now,
        confidence_gate=0.4)


def test_bare_task_defaults_to_due_today(db, stub_embedder, resolver_for_db):
    from io_assistant.models_domain import ExtractedRecord
    from io_assistant.resolve.dates import start_of_day
    res = _persist_one(db, stub_embedder, resolver_for_db,
        ExtractedRecord(kind="task", title="call the dentist", confidence=0.9), NOW)
    row = db.get(__import__("io_assistant.db.models", fromlist=["Record"]).Record,
                 res.record_ids[0])
    assert row.due_at == start_of_day(NOW) and row.status == "open"


def test_someday_task_stays_dateless(db, stub_embedder, resolver_for_db):
    from io_assistant.models_domain import ExtractedRecord
    res = _persist_one(db, stub_embedder, resolver_for_db,
        ExtractedRecord(kind="task", title="learn the cello",
                        when_phrase="someday", confidence=0.9), NOW)
    row = db.get(__import__("io_assistant.db.models", fromlist=["Record"]).Record,
                 res.record_ids[0])
    assert row.due_at is None


def test_event_is_never_defaulted(db, stub_embedder, resolver_for_db):
    from io_assistant.models_domain import ExtractedRecord
    res = _persist_one(db, stub_embedder, resolver_for_db,
        ExtractedRecord(kind="gym_session", title="legs", confidence=0.9), NOW)
    row = db.get(__import__("io_assistant.db.models", fromlist=["Record"]).Record,
                 res.record_ids[0])
    assert row.due_at is None and row.occurred_at is None
```

(If `tests/test_persist_writer.py` lacks a `resolver_for_db` fixture, add one that builds `EntityResolver(db, stub_embedder, config.resolver)`; check how existing writer tests get a resolver and match that.)

- [ ] **Step 2: Run to verify they fail**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_persist_writer.py -k "bare_task or someday or never_defaulted" -q`
Expected: FAIL — `start_of_day` missing and/or `due_at is None` for the bare task.

- [ ] **Step 3: Implement — date helper**

In `io_assistant/resolve/dates.py`, add:

```python
def start_of_day(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)
```

Add `"start_of_day"` to `__all__` if the module has one.

- [ ] **Step 4: Implement — writer**

In `io_assistant/persist/writer.py`, near the top:

```python
import re as _re
from io_assistant.resolve.dates import ground, to_rrule, start_of_day

_SOMEDAY = _re.compile(
    r"\b(someday|some day|eventually|some ?point|no rush|whenever|one day|"
    r"at some point|no hurry)\b", _re.IGNORECASE,
)


def _is_someday(rec) -> bool:
    return bool(_SOMEDAY.search(" ".join(
        p for p in (rec.when_phrase, rec.due_phrase) if p)))
```

In the record loop, replace the `due_at=` line:

```python
        occurred = ground(rec.when_phrase, now).value
        due = ground(rec.due_phrase, now).value
        if (kind in _STATUS_KINDS and due is None and occurred is None
                and not rec.recurrence_phrase and not _is_someday(rec)):
            due = start_of_day(now)

        row = m.Record(
            kind=kind,
            domain=normalize_domain(rec.domain),
            title=rec.title,
            body=rec.body,
            occurred_at=occurred,
            due_at=due,
            recurrence_rule=to_rrule(rec.recurrence_phrase),
            status=status,
            ...
        )
```

- [ ] **Step 5: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_persist_writer.py tests/test_dates.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/persist/writer.py io_assistant/resolve/dates.py tests/test_persist_writer.py
git commit -m "feat(tasks): bare task/chore defaults to due-today; 'someday' stays dateless"
```

---

### Task 11: Read-time roll-forward in `compile_structured`

**Files:**
- Modify: `io_assistant/query/compile.py` (`compile_structured`, ~line 38-73)
- Test: `tests/test_query_compile.py`

**Interfaces:**
- Produces: when `sq.status_filter` includes `"open"` and `sq.target_type == "record"`, an **open** record with `due_at <= now` is always in-window — the `time_window` upper/lower bounds no longer exclude it. A `done`/`dropped` row still obeys the window. Non-task queries (`status_filter` absent) are unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_query_compile.py  (append)
import datetime as dt
from sqlalchemy import and_
from io_assistant.query.compile import compile_structured
from io_assistant.query.plan import SubQuery, TimeWindow
from io_assistant.db import models as m
from tests.conftest import requires_db

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


@requires_db
def test_overdue_open_task_is_in_a_today_window(db):
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    old = m.Record(kind="task", title="overdue thing", status="open",
                   due_at=NOW - dt.timedelta(days=3), source_utterance_id=u.id)
    db.add(old); db.flush()
    sq = SubQuery(target_type="record", status_filter=["open"],
                  time_window=TimeWindow(start=NOW.replace(hour=0),
                                         end=NOW.replace(hour=23, minute=59)))
    rows = db.execute(compile_structured(sq, {}, NOW)).scalars().all()
    assert old.id in {r.id for r in rows}


@requires_db
def test_last_week_query_does_not_pull_an_open_overdue_task(db):
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    t = m.Record(kind="task", title="pay rent", status="open",
                 due_at=NOW - dt.timedelta(days=2), source_utterance_id=u.id)
    e = m.Record(kind="event", title="museum", occurred_at=NOW - dt.timedelta(days=9),
                 source_utterance_id=u.id)
    db.add_all([t, e]); db.flush()
    sq = SubQuery(target_type="record",
                  time_window=TimeWindow(start=NOW - dt.timedelta(days=14),
                                         end=NOW - dt.timedelta(days=7)))
    rows = db.execute(compile_structured(sq, {}, NOW)).scalars().all()
    ids = {r.id for r in rows}
    assert e.id in ids and t.id not in ids
```

- [ ] **Step 2: Run to verify they fail**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_query_compile.py -k overdue -q`
Expected: FAIL on the first test (window excludes the 3-day-old task).

- [ ] **Step 3: Implement**

In `compile_structured`, after the status/kind/entity conds are built and before the `time_window` block:

```python
    open_rollforward = (
        sq.target_type == "record"
        and sq.status_filter is not None
        and "open" in sq.status_filter
    )

    if sq.time_window is not None:
        window = []
        if sq.time_window.start is not None:
            window.append(recency >= sq.time_window.start)
        if sq.time_window.end is not None:
            window.append(recency <= sq.time_window.end)
        if window:
            if open_rollforward:
                conds.append(
                    or_(
                        and_(*window),
                        and_(m.Record.status == "open", m.Record.due_at <= now),
                    )
                )
            else:
                conds.append(and_(*window))
```

Add `or_` to the `sqlalchemy` import.

- [ ] **Step 4: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_query_compile.py tests/test_query_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/query/compile.py tests/test_query_compile.py
git commit -m "feat(tasks): overdue open tasks always in-window (read-time roll-forward)"
```

---

### Task 12: Plan prompt + rank bump for overdue

**Files:**
- Modify: `io_assistant/prompts/plan.txt`
- Modify: `io_assistant/query/rank.py` (`rank`, ~line 65-100)
- Test: `tests/test_query_rank.py`, `tests/test_backend_prompts.py` (or wherever prompt-content assertions live)

**Interfaces:**
- Produces: `plan.txt` instructs — for "what do I need to do / what's on my plate / my tasks / anything due", set `status_filter: ["open"]` and leave `time_window` null unless the user names one. `rank()` gives an open record with `due_at < now` a `+0.2` score component (`components["overdue"]`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_query_rank.py  (append)
import datetime as dt
from io_assistant.query.rank import rank
from io_assistant.query.retrieve import RetrievedRow

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


class _Rec:
    def __init__(self, **kw):
        self.__dict__.update(dict(occurred_at=None, due_at=None, created_at=NOW,
                                  status=None, id=1, **kw))


def test_overdue_open_task_outranks_a_fresh_note():
    overdue = RetrievedRow(_Rec(id=1, status="open",
        due_at=NOW - dt.timedelta(days=4)), "record", "structured", None)
    fresh = RetrievedRow(_Rec(id=2, created_at=NOW), "record", "structured", None)
    ranked = rank([[overdue, fresh]], NOW)
    assert ranked[0].obj.id == 1
    assert ranked[0].components.get("overdue", 0) > 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_query_rank.py -k overdue -q`
Expected: FAIL — no `overdue` component.

- [ ] **Step 3: Implement — rank.py**

In the `rank` loop, after `prov_bonus`:

```python
        overdue = 0.0
        due = getattr(r.obj, "due_at", None)
        if getattr(r.obj, "status", None) == "open" and due is not None:
            if _as_dt(due, now) < now:
                overdue = 0.2
        score = (
            0.30 * recency + 0.30 * similarity + 0.30 * structured_rel
            + prov_bonus + overdue
        )
```

Add `"overdue": overdue` to the `components` dict.

- [ ] **Step 4: Implement — plan.txt**

After the "who is / who are my <group>" rule, add:

```
- "what do I need to do", "what's on my plate", "my tasks", "anything due",
  "what's outstanding" → target_type "record", status_filter ["open"], and
  leave time_window null. Overdue items surface automatically. Only set a
  time_window when the user names one ("due this week", "tasks for today").
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_query_rank.py tests/test_query_pipeline.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/query/rank.py io_assistant/prompts/plan.txt tests/test_query_rank.py
git commit -m "feat(tasks): rank bump for overdue open tasks + plan.txt task rule"
```

---

### Task 13: `overdue` / `due_label` in serialized rows

**Files:**
- Modify: `io_assistant/query/respond.py` (`rows_to_json`)
- Test: `tests/test_query_respond.py`

**Interfaces:**
- Consumes: the phrasing-model row dicts built by `rows_to_json`.
- Produces: each record row dict also carries `overdue: bool` (status `open` and `due_at < now`) and `due_label: str | None` — a human phrase computed in Python ("today", "yesterday", "in 3 days", "Fri 12 Sep", "2 days ago"). The phrasing model never does date math.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_query_respond.py  (append)
def test_rows_to_json_marks_overdue_and_labels_due(fake_backend):
    import datetime as dt
    from io_assistant.query.respond import rows_to_json
    now = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)

    class R:
        id = 1; title = "pay rent"; kind = "task"; domain = "home"
        status = "open"; due_at = now - dt.timedelta(days=2)
        occurred_at = None; body = None; notes = None; attributes = {}

    out = rows_to_json([_ranked(R())], now)   # match the helper used by sibling tests
    assert out[0]["overdue"] is True
    assert "ago" in out[0]["due_label"]
```

(Use whatever wrapper the existing `test_query_respond.py` tests use to turn a fake row into what `rows_to_json` consumes — mirror a sibling test exactly.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_query_respond.py -k overdue -q`
Expected: FAIL — keys absent.

- [ ] **Step 3: Implement**

Add a helper in `respond.py`:

```python
def _due_label(due: datetime | None, now: datetime) -> str | None:
    if due is None:
        return None
    days = (due.date() - now.date()).days
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    if days == -1:
        return "yesterday"
    if days < 0:
        return f"{-days} days ago"
    if days <= 6:
        return due.strftime("%a")
    return due.strftime("%a %d %b")
```

In the per-record dict build in `rows_to_json`, add:

```python
        "overdue": bool(getattr(obj, "status", None) == "open"
                        and getattr(obj, "due_at", None) is not None
                        and obj.due_at < now),
        "due_label": _due_label(getattr(obj, "due_at", None), now),
```

(Confirm `rows_to_json` receives `now` — if not, thread it from the `Responder.run` call; a sibling change in the same file.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_query_respond.py tests/test_query_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/query/respond.py tests/test_query_respond.py
git commit -m "feat(tasks): overdue flag + human due_label in phrasing rows"
```

**PHASE 2 CHECKPOINT** — full suite green. Merge point.

---

# Phase 3 — Collections registry (storage + learning)

Ships: adding an item to a novel list writes the item *and* a `collections` descriptor the rest of the system can consult.

---

### Task 14: Migration 0009 + `Collection` ORM model

**Files:**
- Create: `io_assistant/db/migrations/versions/0009_collections.py`
- Modify: `io_assistant/db/models.py` (add `Collection`)
- Test: `tests/test_migrations.py`

**Interfaces:**
- Produces: table `collections(id, name, kind_slug UNIQUE, item_noun, synonyms jsonb '[]', field_hint jsonb '{}', example_record_id → records.id ON DELETE SET NULL, created_at, updated_at)`; ORM `Collection` with those attrs.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_migrations.py  (append)
def test_collections_table_exists(engine):
    from sqlalchemy import inspect
    t = inspect(engine)
    assert "collections" in t.get_table_names()
    cols = {c["name"] for c in t.get_columns("collections")}
    assert {"kind_slug", "synonyms", "field_hint", "item_noun"} <= cols
```

- [ ] **Step 2: Run to verify it fails**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_migrations.py::test_collections_table_exists -q`
Expected: FAIL.

- [ ] **Step 3: Write the migration**

```python
# io_assistant/db/migrations/versions/0009_collections.py
"""collections: learned descriptors for ad-hoc user lists

A row is created the first time the extraction model flags a record as an item
in a personal list that is not event/task/chore (movies to watch, books to
read, gift ideas). Keyed by the records.kind slug those items share; synonyms
and item_noun feed the plan/decide prompts so the list stays findable.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-10
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind_slug", sa.Text(), nullable=False),
        sa.Column("item_noun", sa.Text(), nullable=True),
        sa.Column("synonyms", JSONB(), nullable=False,
                  server_default=sa.text("'[]'::jsonb")),
        sa.Column("field_hint", JSONB(), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("example_record_id", sa.BigInteger(),
                  sa.ForeignKey("records.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_collections_kind_slug", "collections", ["kind_slug"],
                    unique=True)


def downgrade() -> None:
    op.drop_index("ix_collections_kind_slug", table_name="collections")
    op.drop_table("collections")
```

- [ ] **Step 4: Add the ORM model**

In `io_assistant/db/models.py` (near `Record`):

```python
class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind_slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    item_noun: Mapped[str | None] = mapped_column(Text, nullable=True)
    synonyms: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    field_hint: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    example_record_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("records.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False)
```

(Match the import style already in `models.py` for `JSONB`, `text`, `BigInteger`, `ForeignKey`.)

- [ ] **Step 5: Run migration + test + down/up**

Run:
```bash
IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run pytest tests/test_migrations.py -q
IO_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run alembic downgrade 0008
IO_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run alembic upgrade head
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/db/migrations/versions/0009_collections.py io_assistant/db/models.py tests/test_migrations.py
git commit -m "feat(collections): migration 0009 — collections table + ORM model"
```

---

### Task 15: `ExtractedCollection` + extraction schema field

**Files:**
- Modify: `io_assistant/models_domain.py` (`ExtractedCollection`, `ExtractedRecord.collection`)
- Modify: `io_assistant/extract/schema.py` (`SCHEMA_JSON`, `_EXAMPLES`)
- Test: `tests/test_extract_schema.py`, `tests/test_models_domain.py`

**Interfaces:**
- Produces:
  - `class ExtractedCollection(BaseModel): name: str; item_noun: str | None = None; synonyms: list[str] = []; checkable: bool = False`
  - `ExtractedRecord.collection: ExtractedCollection | None = None`
  - `SCHEMA_JSON` documents the optional `collection` key; one new few-shot pair whose OUTPUT parses as `ExtractionResult`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_models_domain.py  (append)
def test_extracted_record_accepts_a_collection():
    from io_assistant.models_domain import ExtractedRecord, ExtractedCollection
    r = ExtractedRecord(kind="watchlist", title="Dune", confidence=0.9,
        collection=ExtractedCollection(name="watchlist", item_noun="movie",
                                       synonyms=["movies to watch"], checkable=True))
    assert r.collection.checkable is True
```

```python
# tests/test_extract_schema.py  (append — mirror the existing "every example parses" test)
def test_new_watchlist_example_parses():
    from io_assistant.extract.schema import _EXAMPLES
    from io_assistant.models_domain import ExtractionResult
    outs = [ExtractionResult.model_validate(out) for _, out in _EXAMPLES]
    assert any(
        rec.collection is not None
        for res in outs for rec in res.records
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_models_domain.py tests/test_extract_schema.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement — models**

In `io_assistant/models_domain.py`, before `ExtractedRecord`:

```python
class ExtractedCollection(BaseModel):
    name: str
    item_noun: str | None = None
    synonyms: list[str] = Field(default_factory=list)
    checkable: bool = False
```

In `ExtractedRecord`, add:

```python
    collection: ExtractedCollection | None = None
```

- [ ] **Step 4: Implement — schema hint + example**

In `io_assistant/extract/schema.py`, extend the `records:` line block in `SCHEMA_JSON`:

```
           "attributes": {}, "confidence": 0..1,
           "collection": {"name": str, "item_noun": str, "synonyms": [str], "checkable": bool} | null}]
```

and add a guidance line:

```
collection: set ONLY when this record is an item the user is adding to a
      personal list that is not event/task/chore (movies/shows to watch, books
      to read, gift ideas, restaurants to try). Use the SAME kind slug you would
      use to ask for the whole list. "checkable": true if items get watched /
      read / done. Fill it on the first item; you may omit it on later items.
```

Append to `_EXAMPLES`:

```python
    (
        "add Dune Part Two to my list of movies I want to watch",
        {"people": [], "places": [], "items": [], "occasions": [],
         "records": [{"kind": "watchlist", "domain": "other",
                      "title": "Dune Part Two", "status": "open",
                      "collection": {"name": "watchlist", "item_noun": "movie or show",
                                     "synonyms": ["movies to watch", "shows to watch", "watchlist"],
                                     "checkable": True},
                      "attributes": {"medium": "movie"}, "confidence": 0.9}]},
    ),
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_extract_schema.py tests/test_models_domain.py tests/test_extractor.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/models_domain.py io_assistant/extract/schema.py tests/test_models_domain.py tests/test_extract_schema.py
git commit -m "feat(collections): extraction schema — optional collection descriptor on a record"
```

---

### Task 16: `collections/registry.py`

**Files:**
- Create: `io_assistant/collections/__init__.py` (empty)
- Create: `io_assistant/collections/registry.py`
- Test: `tests/test_collections_registry.py`

**Interfaces:**
- Consumes: `m.Collection`, `ExtractedCollection`, `normalize_kind`, `rapidfuzz.fuzz`.
- Produces:
  - `upsert_collection(session, *, kind_slug: str, proposal: ExtractedCollection, example_record_id: int | None, now: datetime) -> m.Collection` — insert if new; else union synonyms (lowercased, deduped, includes `name` and `kind_slug`), keep earliest `name`/`item_noun` unless null, merge `field_hint`, set `example_record_id` if currently null, bump `updated_at`.
  - `describe_collections(session) -> str` — `""` if none; else up to 20 lines: `- watchlist — movie or show (say: "movies to watch", "shows to watch")`.
  - `resolve_collection(session, phrase: str) -> m.Collection | None` — exact `kind_slug`; then exact synonym; then `fuzz.WRatio ≥ 82` over name+synonyms.
  - `checkable_kinds(session) -> set[str]` — `{c.kind_slug for c in collections if c.field_hint.get("checkable")}`.
  - (Task 18 adds `seen_kinds(session, *, limit=12) -> list[str]` and `routing_preamble(session) -> str` to this same module.)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_collections_registry.py
import datetime as dt

from io_assistant.collections.registry import (
    upsert_collection, describe_collections, resolve_collection, checkable_kinds,
)
from io_assistant.models_domain import ExtractedCollection
from tests.conftest import requires_db

NOW = dt.datetime(2026, 9, 10, 12, 0, tzinfo=dt.timezone.utc)


def _prop(**kw):
    kw.setdefault("name", "watchlist")
    kw.setdefault("synonyms", ["movies to watch", "shows to watch"])
    kw.setdefault("checkable", True)
    return ExtractedCollection(item_noun="movie or show", **kw)


@requires_db
def test_first_item_creates_the_collection(db):
    c = upsert_collection(db, kind_slug="watchlist", proposal=_prop(),
                          example_record_id=None, now=NOW)
    assert c.kind_slug == "watchlist" and "movies to watch" in c.synonyms


@requires_db
def test_second_item_merges_synonyms_no_duplicate(db):
    upsert_collection(db, kind_slug="watchlist", proposal=_prop(), example_record_id=None, now=NOW)
    c = upsert_collection(db, kind_slug="watchlist",
                          proposal=_prop(synonyms=["films to see", "movies to watch"]),
                          example_record_id=None, now=NOW)
    assert sorted(c.synonyms) == sorted(set(c.synonyms))
    assert "films to see" in c.synonyms and c.name == "watchlist"
    assert db.query(type(c)).count() == 1


@requires_db
def test_resolve_by_slug_synonym_and_fuzzy(db):
    upsert_collection(db, kind_slug="watchlist", proposal=_prop(), example_record_id=None, now=NOW)
    assert resolve_collection(db, "watchlist").kind_slug == "watchlist"
    assert resolve_collection(db, "shows to watch").kind_slug == "watchlist"
    assert resolve_collection(db, "movies i wanna watch").kind_slug == "watchlist"
    assert resolve_collection(db, "grocery list") is None


@requires_db
def test_describe_and_checkable(db):
    upsert_collection(db, kind_slug="watchlist", proposal=_prop(), example_record_id=None, now=NOW)
    upsert_collection(db, kind_slug="restaurants",
                      proposal=ExtractedCollection(name="restaurants", item_noun="place",
                                                   synonyms=["places to eat"], checkable=False),
                      example_record_id=None, now=NOW)
    text = describe_collections(db)
    assert "watchlist" in text and "restaurants" in text
    assert checkable_kinds(db) == {"watchlist"}
```

- [ ] **Step 2: Run to verify they fail**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_collections_registry.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# io_assistant/collections/__init__.py
```

```python
# io_assistant/collections/registry.py
from __future__ import annotations

from datetime import datetime

from rapidfuzz import fuzz
from sqlalchemy import select

from io_assistant.db import models as m
from io_assistant.models_domain import ExtractedCollection, normalize_kind

__all__ = ["upsert_collection", "describe_collections", "resolve_collection",
           "checkable_kinds"]

_MAX_LINES = 20
_FUZZY = 82


def _norm_syn(xs) -> list[str]:
    seen: dict[str, None] = {}
    for x in xs:
        s = str(x).strip().lower()
        if s:
            seen.setdefault(s, None)
    return list(seen)


def upsert_collection(session, *, kind_slug: str, proposal: ExtractedCollection,
                      example_record_id: int | None, now: datetime) -> m.Collection:
    slug = normalize_kind(kind_slug)
    row = session.execute(
        select(m.Collection).where(m.Collection.kind_slug == slug)
    ).scalars().first()
    syns = _norm_syn([*proposal.synonyms, proposal.name, slug])
    if row is None:
        row = m.Collection(
            name=proposal.name.strip() or slug,
            kind_slug=slug,
            item_noun=(proposal.item_noun or None),
            synonyms=syns,
            field_hint={"checkable": bool(proposal.checkable)},
            example_record_id=example_record_id,
            created_at=now, updated_at=now,
        )
        session.add(row)
        session.flush()
        return row
    row.synonyms = _norm_syn([*row.synonyms, *syns])
    if not row.item_noun and proposal.item_noun:
        row.item_noun = proposal.item_noun
    fh = dict(row.field_hint or {})
    fh.setdefault("checkable", bool(proposal.checkable))
    row.field_hint = fh
    if row.example_record_id is None and example_record_id is not None:
        row.example_record_id = example_record_id
    row.updated_at = now
    session.flush()
    return row


def describe_collections(session) -> str:
    rows = session.execute(
        select(m.Collection).order_by(m.Collection.created_at)
    ).scalars().all()[:_MAX_LINES]
    if not rows:
        return ""
    out = []
    for c in rows:
        say = ", ".join(f'"{s}"' for s in c.synonyms[:4]) or f'"{c.name}"'
        noun = f" — {c.item_noun}" if c.item_noun else ""
        out.append(f"- {c.kind_slug}{noun} (say: {say})")
    return "\n".join(out)


def resolve_collection(session, phrase: str):
    p = (phrase or "").strip().lower()
    if not p:
        return None
    rows = session.execute(select(m.Collection)).scalars().all()
    for c in rows:
        if c.kind_slug == normalize_kind(p) or p in {s.lower() for s in c.synonyms}:
            return c
    best, best_c = 0.0, None
    for c in rows:
        for cand in (c.name, *c.synonyms):
            sc = fuzz.WRatio(p, cand)
            if sc > best:
                best, best_c = sc, c
    return best_c if best >= _FUZZY else None


def checkable_kinds(session) -> set[str]:
    return {
        c.kind_slug
        for c in session.execute(select(m.Collection)).scalars().all()
        if (c.field_hint or {}).get("checkable")
    }
```

- [ ] **Step 4: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_collections_registry.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/collections/ tests/test_collections_registry.py
git commit -m "feat(collections): registry — upsert, describe, resolve, checkable_kinds"
```

---

### Task 17: Writer upserts the collection + checkable status default

**Files:**
- Modify: `io_assistant/persist/writer.py` (record loop)
- Modify: `io_assistant/orchestrator.py` (`_checkable_kinds` — add the registry)
- Test: `tests/test_persist_writer.py`, `tests/test_orchestrator_tasks.py`

**Interfaces:**
- Consumes: `upsert_collection`, `checkable_kinds` (Task 16).
- Produces: storing a record with `rec.collection` set → a `collections` row (via `upsert_collection`) with `example_record_id` = the new record id; and if `rec.collection.checkable` (or `kind` already in `checkable_kinds(session)`), the record's `status` defaults to `"open"` when the model left it null. `_checkable_kinds` now returns `{"task","chore"} | checkable_kinds(session)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_persist_writer.py  (append)
def test_storing_a_watchlist_item_registers_the_collection(db, stub_embedder, resolver_for_db):
    from io_assistant.models_domain import ExtractedRecord, ExtractedCollection
    from io_assistant.db import models as m
    res = _persist_one(db, stub_embedder, resolver_for_db, ExtractedRecord(
        kind="watchlist", title="Oppenheimer", confidence=0.9,
        collection=ExtractedCollection(name="watchlist", item_noun="movie",
            synonyms=["movies to watch"], checkable=True)), NOW)
    row = db.get(m.Record, res.record_ids[0])
    assert row.status == "open"
    c = db.query(m.Collection).filter_by(kind_slug="watchlist").one()
    assert c.example_record_id == row.id
```

```python
# tests/test_orchestrator_tasks.py  (append)
@requires_db
def test_watched_it_closes_a_checkable_collection_item(config, db, fake_backend):
    from io_assistant.db import models as m
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    c = m.Collection(kind_slug="watchlist", name="watchlist",
                     synonyms=["watchlist", "movies to watch"],
                     field_hint={"checkable": True})
    r = m.Record(kind="watchlist", title="Dune Part Two", status="open",
                 source_utterance_id=u.id)
    db.add_all([c, r]); db.flush()
    res = _orch(config, db, fake_backend).handle("I watched Dune Part Two", captured_at=NOW)
    db.refresh(r)
    assert r.status == "done" and res.intent_kind == "ack"
```

- [ ] **Step 2: Run to verify they fail**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_persist_writer.py -k watchlist tests/test_orchestrator_tasks.py -k watched -q`
Expected: FAIL.

- [ ] **Step 3: Implement — writer**

In the record loop, after `session.flush()` that assigns `row.id`:

```python
        if rec.collection is not None:
            from io_assistant.collections.registry import upsert_collection
            upsert_collection(session, kind_slug=rec.kind, proposal=rec.collection,
                              example_record_id=row.id, now=now)
```

And change the `status` computation near the top of the loop:

```python
        from io_assistant.collections.registry import checkable_kinds as _ck
        checkable = kind in _STATUS_KINDS or kind in _ck(session)
        if rec.collection is not None and rec.collection.checkable:
            checkable = True
        status = "open" if checkable and rec.status is None else rec.status
```

(One `_ck(session)` call per store is cheap — `collections` is tiny. If the writer is hot, memoize on the session; not needed now.)

- [ ] **Step 4: Implement — orchestrator `_checkable_kinds`**

```python
    def _checkable_kinds(self, session) -> set[str]:
        from io_assistant.collections.registry import checkable_kinds
        return {"task", "chore"} | checkable_kinds(session)
```

- [ ] **Step 5: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_persist_writer.py tests/test_orchestrator_tasks.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/persist/writer.py io_assistant/orchestrator.py tests/test_persist_writer.py tests/test_orchestrator_tasks.py
git commit -m "feat(collections): writer registers the collection; checkable items get status=open"
```

**PHASE 3 CHECKPOINT** — full suite green. Merge point.

---

# Phase 4 — Collections-aware routing

Ships: "what's on my watchlist" / "films I haven't seen" resolve to the same records however phrased.

---

### Task 18: Inject the vocabulary into planner context

**Files:**
- Modify: `io_assistant/query/pipeline.py` (`QueryPipeline.answer`)
- Modify: `io_assistant/orchestrator.py` (`_dispatch_step` query branch, `_planner.plan` call ~line 198 — combined decide)
- Test: `tests/test_query_pipeline.py`

**Interfaces:**
- Consumes: `describe_collections` (Task 16).
- Produces: `QueryPipeline.answer` prepends, to the `context` string it passes to `Planner`, a block:

  ```
  Known lists (reuse the exact slug):
  <describe_collections output>

  Seen kinds: giftlist, watchlist, gym_session   (top non-core kind slugs by row count)

  ```

  The `Known lists` block appears when the registry is non-empty; the `Seen kinds`
  line always appears when there are non-core kinds in `records` (spec 4.3 —
  cheap reinforcement so even an unregistered list tends to reuse its slug).
  Same blocks feed the combined `decide` planner. No signature changes — it is
  concatenated into the existing `context` param.
- New helper `seen_kinds(session, *, limit=12) -> list[str]` in
  `io_assistant/collections/registry.py`: `SELECT kind, count(*) FROM records
  GROUP BY kind ORDER BY count(*) DESC`, drop the core kinds
  (`event, task, chore, gym_session, job_meeting, expense, note` — a module
  `_CORE_KINDS` set), take `limit`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_query_pipeline.py  (append)
@requires_db
def test_planner_sees_known_lists_and_seen_kinds_in_context(db, fake_backend, config, stub_embedder):
    from io_assistant.db import models as m
    from io_assistant.query.pipeline import QueryPipeline
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    db.add(m.Collection(kind_slug="watchlist", name="watchlist",
                        synonyms=["watchlist", "movies to watch"], field_hint={}))
    for i in range(3):
        db.add(m.Record(kind="giftlist", title=f"gift {i}", source_utterance_id=u.id))
    db.flush()
    fake_backend.set_plan({"subqueries": [{"target_type": "record"}], "answer_shape": "text"})
    QueryPipeline(fake_backend, stub_embedder, config.resolver).answer(
        db, "what's on my watchlist", NOW, context="prior turn")
    ctx = fake_backend.last_context or ""
    assert "Known lists" in ctx and "watchlist" in ctx
    assert "Seen kinds" in ctx and "giftlist" in ctx
```

- [ ] **Step 2: Run to verify it fails**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_query_pipeline.py -k known_lists -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add a shared helper (used by both the query pipeline and the orchestrator's
decide call) in `io_assistant/collections/registry.py`:

```python
def routing_preamble(session) -> str:
    parts = []
    vocab = describe_collections(session)
    if vocab:
        parts.append("Known lists (reuse the exact slug):\n" + vocab)
    seen = seen_kinds(session)
    if seen:
        parts.append("Seen kinds: " + ", ".join(seen))
    return ("\n\n".join(parts) + "\n\n") if parts else ""
```

In `QueryPipeline.answer`, before `Planner(self._backend).run(...)`:

```python
        from io_assistant.collections.registry import routing_preamble
        plan_ctx = routing_preamble(session) + (context or "") or None
        plan = Planner(self._backend).run(question, now, context=plan_ctx)
```

Keep passing the original `context` to `Responder` (the vocab is only useful to the planner).

For the combined path: in `orchestrator._handle_in_session`, where it calls `self._planner.plan(text, now, context=history)` (~line 198), pass `context=routing_preamble(session) + (history or "") or None`. (The `DecidePlanner` forwards `context` to `backend.decide`.)

- [ ] **Step 4: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_query_pipeline.py tests/test_decide_planner.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/query/pipeline.py io_assistant/orchestrator.py tests/test_query_pipeline.py
git commit -m "feat(collections): feed known-list vocabulary into the planner + decide context"
```

---

### Task 19: Prompt rules for slug reuse

**Files:**
- Modify: `io_assistant/prompts/plan.txt`
- Modify: `io_assistant/prompts/decide.txt`
- Modify: `tests/fixtures/decide_cases.json` (+ 2 cases)
- Test: `tests/test_decide_eval.py` (opt-in — run manually), `tests/test_backend_prompts.py`

**Interfaces:**
- Produces: `plan.txt` — "If the question is about a Known list above, set target_type 'record' and kind_filter to that list's exact slug; never invent a new slug." `decide.txt` — "When the user adds to a list named in Known lists, reuse that slug as `kind`."

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backend_prompts.py  (append; or wherever prompt text is asserted)
def test_plan_prompt_mentions_known_lists():
    from pathlib import Path
    txt = Path("io_assistant/prompts/plan.txt").read_text()
    assert "Known list" in txt and "kind_filter" in txt
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_backend_prompts.py -k known_lists -q`
Expected: FAIL.

- [ ] **Step 3: Implement — plan.txt**

After the tasks rule from Task 12, add:

```
- If the question is about one of the "Known lists" shown above, set
  target_type "record" and kind_filter to that list's exact slug. Reuse the
  slug verbatim — never invent a new one. "what's left to watch" on a
  checkable list also sets status_filter ["open"].
```

- [ ] **Step 4: Implement — decide.txt**

In the `store` bullet, add a sentence:

```
  If the user is adding to a list named under "Known lists" above, use that
  list's exact slug as the record "kind" and you may omit the "collection"
  field (it is already registered).
```

- [ ] **Step 5: Add eval fixtures**

Append to `tests/fixtures/decide_cases.json` (match the file's existing case shape):

```json
{"utterance": "add The Bear to my shows to watch", "expect": {"kind": "store"}},
{"utterance": "what's on my watchlist", "expect": {"kind": "query"}}
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_backend_prompts.py -q`
Expected: PASS. Then, if Ollama/Anthropic available: `IO_DECIDE_EVAL=1 uv run pytest tests/test_decide_eval.py -q` and record the pass rate in the commit message (do not fail the build on it).

- [ ] **Step 7: Commit**

```bash
git add io_assistant/prompts/plan.txt io_assistant/prompts/decide.txt tests/fixtures/decide_cases.json tests/test_backend_prompts.py
git commit -m "feat(collections): plan/decide prompt rules for known-list slug reuse"
```

---

### Task 20: `aggregation == "count"` in `compile_structured`

**Files:**
- Modify: `io_assistant/query/compile.py`
- Modify: `io_assistant/query/retrieve.py` (surface a count) and `io_assistant/query/pipeline.py` (carry it into `QueryAnswer`)
- Test: `tests/test_query_compile.py`, `tests/test_query_pipeline.py`

**Interfaces:**
- Produces: when `sq.aggregation == "count"`, `retrieve_subquery` returns a single synthetic row carrying `count: int` (or `QueryAnswer` gains `count: int | None`). The responder is told "N items" so the phrasing model states the number without counting rows itself.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_query_pipeline.py  (append)
@requires_db
def test_count_aggregation_reports_a_number(db, fake_backend, config, stub_embedder):
    from io_assistant.db import models as m
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    for i in range(4):
        db.add(m.Record(kind="watchlist", title=f"film {i}", status="open",
                        source_utterance_id=u.id))
    db.flush()
    fake_backend.set_plan({"subqueries": [
        {"target_type": "record", "kind_filter": ["watchlist"], "aggregation": "count"}],
        "answer_shape": "text"})
    fake_backend.set_answer("You have 4.")
    ans = __import__("io_assistant.query.pipeline", fromlist=["QueryPipeline"]).QueryPipeline(
        fake_backend, stub_embedder, config.resolver).answer(db, "how many films on my list", NOW)
    assert ans.count == 4
```

- [ ] **Step 2: Run to verify it fails**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_query_pipeline.py -k count_aggregation -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `compile.py`, add `compile_count(sq, entity_ids, now) -> Select` that reuses the same `conds` but `select(func.count()).select_from(model).where(and_(*conds))`. Factor the cond-building into a shared `_conds(sq, entity_ids, now)` helper so `compile_structured` and `compile_count` share it.

In `retrieve_subquery`, at the top:

```python
    if sq.aggregation == "count":
        n = session.execute(compile_count(sq, entity_ids, now)).scalar_one()
        return [RetrievedRow(_Count(n), sq.target_type, "structured", None)]
```

with a module `@dataclass class _Count: count: int` (and `id = -1` so `_project` skips it).

In `pipeline.py`, detect a `_Count` in `final` → set `QueryAnswer.count` and pass `f"{n} items" ` into the responder question/context. Add `count: int | None = None` to `QueryAnswer`.

- [ ] **Step 4: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_query_compile.py tests/test_query_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/query/compile.py io_assistant/query/retrieve.py io_assistant/query/pipeline.py tests/test_query_compile.py tests/test_query_pipeline.py
git commit -m "feat(query): compile the 'count' aggregation branch"
```

---

### Task 21: Open/done split for checkable-collection answers

**Files:**
- Modify: `io_assistant/query/respond.py` (`rows_to_json` / the responder question builder)
- Test: `tests/test_query_respond.py`

**Interfaces:**
- Produces: when the answer's rows are all one checkable collection kind, the serialized payload groups them `{"to_do": [...], "done": [...]}` (or adds a `section` field per row) so the phrasing model can say "11 to watch, 3 watched". Non-collection answers unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_query_respond.py  (append)
def test_checkable_collection_rows_are_split_open_vs_done():
    from io_assistant.query.respond import section_for
    assert section_for("open") == "to_do"
    assert section_for("done") == "done"
    assert section_for(None) == "to_do"
```

(Keep the split logic in a tiny pure helper `section_for(status)` so it is trivially testable; `rows_to_json` calls it and adds `"section"` to each row when the answer is collection-shaped.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_query_respond.py -k checkable -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
def section_for(status: str | None) -> str:
    return "done" if status == "done" else "to_do"
```

In `rows_to_json`, add `"section": section_for(getattr(obj, "status", None))` to each record row. (The phrasing prompt already receives the rows; no prompt change needed — the model groups by the field.)

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_query_respond.py tests/test_query_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/query/respond.py tests/test_query_respond.py
git commit -m "feat(collections): section rows to_do/done for checkable lists"
```

**PHASE 4 CHECKPOINT** — full suite green; run the decide eval manually and note the rate. Merge point.

---

# Phase 5 — Collection surfaces

Ships: a real list view with check-off, records-browser filters, `io list`.

---

### Task 22: `CollectionCard` model + emission

**Files:**
- Modify: `io_assistant/models_domain.py` (`CollectionCard`, add to `Card` union)
- Modify: `io_assistant/orchestrator_cards.py` (`query_cards`)
- Test: `tests/test_orchestrator_cards.py`

**Interfaces:**
- Produces: `class CollectionCard(BaseModel): type="collection"; name: str; item_noun: str | None; kind_slug: str; checkable: bool; items: list[TaskListItem]`. `query_cards` emits it (instead of `TaskListCard`) when every `list_records` row shares a `kind` that matches a `m.Collection.kind_slug`. `query_cards` resolves the collection from `lr` directly — no new field on `QueryAnswer`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator_cards.py  (append)
@requires_db
def test_collection_card_emitted_for_watchlist_answer(db):
    from io_assistant.db import models as m
    from io_assistant.models_domain import CollectionCard
    from io_assistant.query.pipeline import QueryAnswer, RecordRef
    db.add(m.Collection(kind_slug="watchlist", name="watchlist",
                        item_noun="movie", synonyms=["watchlist"],
                        field_hint={"checkable": True}))
    db.flush()
    ans = QueryAnswer(text="", shape="markdown", n_rows=2, source_record_ids=[1, 2],
        list_records=[RecordRef(1, "watchlist", "other", "Dune", "open", None, None),
                      RecordRef(2, "watchlist", "other", "Barbie", "done", None, None)])
    cards = query_cards(db, ans)
    cc = [c for c in cards if isinstance(c, CollectionCard)]
    assert cc and cc[0].kind_slug == "watchlist" and len(cc[0].items) == 2
```

- [ ] **Step 2: Run to verify it fails**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_orchestrator_cards.py -k collection_card -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add `CollectionCard` to `models_domain.py` and to the `Card` union. In `query_cards`:

```python
    from io_assistant.collections.registry import resolve_collection
    slugs = {r.kind for r in lr}
    if lr and len(slugs) == 1:
        c = session.execute(
            select(m.Collection).where(m.Collection.kind_slug == next(iter(slugs)))
        ).scalars().first()
        if c is not None:
            cards.append(CollectionCard(
                name=c.name, item_noun=c.item_noun, kind_slug=c.kind_slug,
                checkable=bool((c.field_hint or {}).get("checkable")),
                items=[TaskListItem(record_id=r.record_id, title=r.title,
                                    status=r.status, due=r.due) for r in lr],
            ))
            return cards   # collection card replaces the tasklist card
```

(Place this check *before* the `TaskListCard` block.)

- [ ] **Step 4: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_orchestrator_cards.py tests/test_query_pipeline.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/models_domain.py io_assistant/orchestrator_cards.py io_assistant/query/pipeline.py tests/test_orchestrator_cards.py
git commit -m "feat(collections): CollectionCard for single-list answers"
```

---

### Task 23: Frontend `collection` card with check-off + add

**Files:**
- Modify: `frontend/components/card.js`
- Modify: `frontend/app.css`
- Test: `tests/test_frontend_library.py`

**Interfaces:**
- Consumes: `ctx.api.editRecord`, `ctx.sendTurn`-equivalent (the card lives in `conversation.js`, which has `sendTurn`); pass an `onAsk(text)` through `ctx` or reuse the existing pattern the `files` card uses to trigger a follow-up turn.
- Produces: `card.type === "collection"` → a titled list; each item row has the same `.task-check` when `card.checkable`; a footer `+ add <item_noun>` input that on Enter calls the conversation's send with `add <value> to my <name>`.

- [ ] **Step 1: Write the failing test**

```python
def test_collection_card_renders_with_add_field():
    src = (FRONTEND / "components" / "card.js").read_text()
    assert 'card.type === "collection"' in src or "collection" in src
    assert "card-collection" in src
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_frontend_library.py -k collection_card -q`
Expected: FAIL.

- [ ] **Step 3: Implement — card.js**

Add a branch:

```javascript
  } else if (card.type === "collection") {
    el.className = "card card-collection";
    el.innerHTML = `
      <div class="cc-head">${escape(card.name)}<span class="mono">${card.items.length}</span></div>
      <div class="cc-list">${card.items.map((it) => `
        <div class="task-row" data-id="${it.record_id}">
          ${card.checkable ? `<button class="task-check" aria-pressed="${it.status === "done"}" aria-label="Toggle">${icon(it.status === "done" ? "checkCircle" : "circle", { size: 14 })}</button>` : `<span class="cc-dot"></span>`}
          <span class="task-t${it.status === "done" ? " done" : ""}">${escape(it.title)}</span>
        </div>`).join("")}</div>
      <form class="cc-add"><input type="text" placeholder="Add ${escape(card.item_noun || "item")}" /></form>`;
    if (ctx) {
      // check-off — same handler as the tasklist branch (extract to a shared
      // wireChecks(el, ctx) helper in this file and call it from both branches)
      wireChecks(el, ctx);
      el.querySelector(".cc-add").addEventListener("submit", (e) => {
        e.preventDefault();
        const v = e.target.querySelector("input").value.trim();
        if (v && ctx.onAsk) { ctx.onAsk(`add ${v} to my ${card.name}`); e.target.reset(); }
      });
    }
```

Extract the checkbox wiring from Task 8 into `function wireChecks(root, ctx) { ... }` in `card.js` and call it from both the `tasklist` and `collection` branches (DRY).

In `frontend/views/conversation.js`, set `ctx.onAsk = (t) => sendTurn(ctx, t);` near where `ctx.onProgress` is set.

- [ ] **Step 4: Implement — app.css**

```css
.card-collection { display: flex; flex-direction: column; gap: 8px; }
.cc-head { display: flex; justify-content: space-between; font-weight: 500; }
.cc-head .mono { color: var(--ink-3); }
.cc-list { display: flex; flex-direction: column; gap: 4px; }
.cc-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--ink-3); flex: none; margin: 0 8px; }
.cc-add input { width: 100%; border: 0; background: var(--fill-2); border-radius: 8px; padding: 8px 10px; color: var(--ink); font: inherit; }
```

- [ ] **Step 5: Run checks**

Run: `node --check frontend/components/card.js && node --check frontend/views/conversation.js && uv run pytest tests/test_frontend_library.py -q`
Expected: PASS + "JS OK".

- [ ] **Step 6: Commit**

```bash
git add frontend/components/card.js frontend/views/conversation.js frontend/app.css tests/test_frontend_library.py
git commit -m "feat(collections): CollectionCard frontend — check-off + inline add"
```

---

### Task 24: Records-browser collection filter chips

**Files:**
- Modify: `frontend/views/records.js`
- Modify: `io_assistant/service/app.py` (`GET /records` already accepts `kind`; add `GET /collections` listing)
- Test: `tests/test_service_entity.py`, `tests/test_frontend_library.py`

**Interfaces:**
- Produces: `GET /collections` → `[{kind_slug, name, item_noun, open_count, done_count}]`. `records.js` renders one filter chip per collection; clicking filters the list by `kind`.

- [ ] **Step 1: Write the failing test**

```python
@requires_db
def test_collections_endpoint_lists_with_counts(config, fake_backend, db):
    from io_assistant.db import models as m
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    db.add(m.Collection(kind_slug="watchlist", name="watchlist", synonyms=["watchlist"], field_hint={"checkable": True}))
    db.add(m.Record(kind="watchlist", title="A", status="open", source_utterance_id=u.id))
    db.add(m.Record(kind="watchlist", title="B", status="done", source_utterance_id=u.id))
    db.flush()
    app = create_app(config, orchestrator=Orchestrator(config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        rows = c.get("/collections").json()
    w = next(r for r in rows if r["kind_slug"] == "watchlist")
    assert w["open_count"] == 1 and w["done_count"] == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_service_entity.py -k collections_endpoint -q`
Expected: FAIL — 404.

- [ ] **Step 3: Implement — endpoint**

```python
    @app.get("/collections")
    def collections_list():
        with factory() as s:
            out = []
            for c in s.execute(select(m.Collection).order_by(m.Collection.created_at)).scalars():
                base = select(func.count()).select_from(m.Record).where(m.Record.kind == c.kind_slug)
                out.append({
                    "kind_slug": c.kind_slug, "name": c.name, "item_noun": c.item_noun,
                    "open_count": s.execute(base.where(m.Record.status == "open")).scalar_one(),
                    "done_count": s.execute(base.where(m.Record.status == "done")).scalar_one(),
                })
            return out
```

- [ ] **Step 4: Implement — records.js**

Add `ctx.api.collections()` to `frontend/api.js` (`GET /collections`). In `records.js`, after loading records, fetch collections and render chips next to the domain filters; a chip click sets the active `kind` filter and re-renders.

- [ ] **Step 5: Run checks**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_service_entity.py -q && node --check frontend/views/records.js && node --check frontend/api.js`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/service/app.py frontend/views/records.js frontend/api.js tests/test_service_entity.py
git commit -m "feat(collections): GET /collections + records-browser filter chips"
```

---

### Task 25: `io list` CLI

**Files:**
- Modify: `io_assistant/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `resolve_collection`, `describe_collections`, a structured query.
- Produces: `io list` → registered collections + `open/done` counts; `io list <name>` → items (open first). Read-only.

- [ ] **Step 1: Write the failing test**

```python
@requires_db
def test_io_list_shows_collections(db, capsys, monkeypatch):
    # mirror how other test_cli.py tests build a session_factory + invoke the command
    ...
    assert "watchlist" in capsys.readouterr().out
```

(Match `tests/test_cli.py`'s existing invocation pattern exactly — it has helpers for a temp DB session and calling subcommands.)

- [ ] **Step 2: Run to verify it fails**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_cli.py -k io_list -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

Add a `list` subcommand to the CLI arg parser and a `_cmd_list(args)` that opens a session, and either prints `describe_collections` + counts, or resolves `args.name` and prints its records ordered `status="open"` first then title.

- [ ] **Step 4: Run tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_cli.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/cli.py tests/test_cli.py
git commit -m "feat(collections): io list CLI"
```

---

### Task 26: Knowledge docs + state

**Files:**
- Create: `.claude/knowledge/tasks-and-collections.md`
- Modify: `.claude/knowledge/query-pipeline.md`, `.claude/knowledge/data-model.md`
- Modify: `.claude/state/session.md`, `.claude/state/backlog.md`, `.claude/state/completed.md`

- [ ] **Step 1: Write `.claude/knowledge/tasks-and-collections.md`**

Cover: the `close_record` lexical path and its two entry points (precheck regexes + `complete_record` capability); `set_record_status` as the sole status mutation + `completed_at`; the default-today rule and `_is_someday`; the read-time roll-forward OR-clause in `compile_structured` and the `rank` bump; the `collections` table, `ExtractedRecord.collection`, `upsert_collection`, and where `describe_collections` is injected (`plan.txt` context + decide context); `checkable_kinds`; `CollectionCard`. Note the deferred items from the spec.

- [ ] **Step 2: Update the other knowledge docs**

`query-pipeline.md` — the roll-forward rule, `kind_filter` from the registry, the `count` branch. `data-model.md` — `records.completed_at`, the `collections` table.

- [ ] **Step 3: Update state**

`session.md` — a "Tasks & Collections — implemented" section with the final suite count. Move the spec/backlog line from `backlog.md` to `completed.md` (dated, newest first).

- [ ] **Step 4: Commit**

```bash
git add .claude/
git commit -m "docs(tasks): knowledge + state for tasks & collections"
```

**PHASE 5 CHECKPOINT** — full suite green (`--deselect` the known-flaky standby test). Run `.\dev.ps1 up` and sanity-check live: "I need to X" → due today; check it off in the tasklist card; "add X to my movies to watch" then "what's on my watchlist". Then `finishing-a-development-branch`.

---

## Self-Review

**Spec coverage:**

| Spec section | Task(s) |
|---|---|
| 1.1 kind aliases | 1 |
| 1.2 `close_record` | 4 (+ 3 for the mutation helper) |
| 1.3 orchestrator precheck + capability | 5, 6 |
| 1.4 ambiguity gate | 5 |
| 1.5 `records.completed_at` | 2, 3, 7 |
| 1.6 interactive checkbox | 8 |
| 1.7 `query_cards` widening | 9 |
| 2.1 default-today | 10 |
| 2.2 roll-forward | 11 |
| 2.3 ranking | 12 |
| 2.4 card / phrasing (`overdue`, `due_label`) | 12 (card text), 13 |
| 3.1 `collections` schema | 14 |
| 3.2 extraction `collection` field | 15 |
| 3.3 deterministic upsert | 16, 17 |
| 3.4 status for collection items | 17 |
| 4.1 prompt injection | 18, 19 |
| 4.2 retrieval + count | 19, 20 |
| 4.3 fallback vocabulary (distinct kinds) | 18 (`seen_kinds` + `routing_preamble`) |
| 5.1 `CollectionCard` | 22, 23 |
| 5.2 records-browser filter | 24 |
| 5.3 `io list` | 25 |
| Cross-cutting: knowledge/state | 26 |

**Placeholder scan:** Task 13, 21, 25 tests say "mirror a sibling test" / "match the file's pattern" for the test *harness wiring* (fixture plumbing that differs per module) — the *assertions* and implementation code are concrete. Task 17 Step 3 imports inside the loop (acceptable here — avoids a circular import between `persist` and `collections`; note it).

**Type consistency:** `close_record(session, phrase, now, *, checkable_kinds, target_status="done")` — same in Tasks 4, 5, 17. `set_record_status(session, record, status, now)` — Tasks 3, 5, 7, 17. `CloseOutcome.status` ∈ {matched, ambiguous, none} and `.record` / `.candidates` — Tasks 4, 5. `PendingComplete(candidate_ids, target_status)` — Task 5. `upsert_collection(session, *, kind_slug, proposal, example_record_id, now)` — Tasks 16, 17. `describe_collections(session) -> str`, `checkable_kinds(session) -> set[str]`, `resolve_collection(session, phrase)`, `seen_kinds(session, *, limit=12)`, `routing_preamble(session) -> str` — module `io_assistant/collections/registry.py`, defined in Tasks 16/18, consumed in 17, 18, 22, 24, 25. `CollectionCard` fields — Tasks 22, 23. `QueryAnswer` gains `count` (Task 20); Task 22 resolves the collection from `list_records` directly, no new `QueryAnswer` field.

All issues fixed inline above.
