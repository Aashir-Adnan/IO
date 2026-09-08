# IO Phase 5 — Conversational Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The service remembers the conversation and feeds it back to the model, replies to a STORE with a natural sentence instead of a template, moves voice server-side behind `POST /voice`, returns structured `cards`, and exposes the data the Nocturne client's Standby and Memory-Inspector panels need — all without touching the deterministic pipeline or the LLM boundary.

**Architecture:** A `conversation/` layer (two new tables + an in-memory turn buffer) sits in the service. Each turn: append the user message → format the last ~6 turns → `Orchestrator.handle(text, history=…)` → append the assistant message. The `Backend` protocol gains an optional `context` string on `route`/`plan`/`phrase` and a new `acknowledge()`. Whisper + Piper load lazily inside the service. Everything the model returns is still routed through the same deterministic resolve/persist/compile/rank code.

**Tech Stack:** Python 3.11+, `uv`, SQLAlchemy 2.x + Alembic, FastAPI, `faster-whisper`, `piper-tts`, `pytest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-io-phase-1.5-conversational-shell.md` — the primary reference. Also `docs/superpowers/specs/2026-09-07-io-phase-1-design.md` §13 (backend), and `.claude/knowledge/` (architecture, query-pipeline, model-backends, desktop-app).

## Global Constraints

- **Python** ≥ 3.11, `uv` for everything (`uv run pytest`, `uv run alembic`).
- **Local-first:** the service binds `127.0.0.1`. Whisper and Piper are local; the only sanctioned non-local call is the Anthropic backend when configured. `tests/test_e2e_store.py`'s socket guard must keep passing.
- **LLM boundary (hard rule):** the model does route / extract / plan / phrase / **acknowledge** only. `acknowledge` may only restate facts `persist_store` actually wrote — it never decides identity, dates, or storage. Conversation context is a read-only string handed to the model; the model's output still flows through the deterministic layers.
- **Migrations:** every schema change is an Alembic migration. This plan adds `0003`.
- **TDD:** failing test first, watch it fail, minimal implementation, watch it pass, commit. Never mock the database — `@requires_db` tests run against the real PostgreSQL named by `IO_TEST_DATABASE_URL`. Backend calls use `FakeBackend`; SQL / resolver / ranking layers never are. Whisper/Piper adapters use `@pytest.mark.voice` (opt-in `IO_VOICE_TESTS=1`); everything else uses `FakeTranscriber` / `FakeSpeaker`.
- **The CLI keeps working.** `io repl` / `io store` call `Orchestrator.handle` with `history=None`; the Orchestrator never touches the conversation tables — the service owns them.
- Tests need `IO_TEST_DATABASE_URL` exported (`.\dev.ps1 test` sets it). DB is docker compose Postgres+pgvector on `:5432`.

---

## File Structure

```
io_assistant/
  db/migrations/versions/0003_conversations.py   # conversations + messages tables
  conversation/
    __init__.py
    store.py        # ConversationStore: CRUD + recent_turns + history + list
    context.py      # Turn, format_context()
  models_domain.py  # + Card types (RecordCard, TaskListCard, SourcesCard, EntityRef)
  backend/
    interface.py    # + context= on route/plan/phrase, + acknowledge()
    local.py        # implement the new signatures
    anthropic_backend.py
    hybrid.py
  prompts/
    route.txt  plan.txt  respond.txt   # + {context} slot
    acknowledge.txt                     # new
  orchestrator.py   # handle(history=…); acknowledge + fallback; build cards
  extract/
    acknowledge.py  # build_fact_list(persist_result, extraction, session) -> str
  speak/
    piper.py        # sentence-wise synth + pacing + SynthesisConfig
    speech_text.py  # prep_for_speech(): abbreviations, pauses
  service/
    schemas.py      # TurnResponse, cards, conversation DTOs, VoiceOut, StandbyOut, EntityOut
    app.py          # ConversationStore wiring; _run reshape; /voice; /conversation(s); /entity; /standby
    voice.py        # lazy Whisper/Piper holder for the service
  config.py         # + UiConfig; + [voice] synthesis keys
  cli.py            # io listen -> POST /voice
  voice/
    loop.py         # VoiceLoop calls the service /voice
tests/
  test_conversation_store.py
  test_conversation_context.py
  test_backend_context.py         # context threading + acknowledge, all backends
  test_orchestrator_conversation.py
  test_service_conversation.py     # two-turn persistence + follow-up context + cards
  test_service_voice.py
  test_speak_natural.py            # prep_for_speech + sentence split
  test_voice_loop.py               # updated for the service client
  test_service_entity.py
  test_service_standby.py
  fixtures/audio/hello.wav         # already exists
```

---

## Task 1: `0003` migration + `ConversationStore` + context formatter

**Files:**
- Create: `io_assistant/db/migrations/versions/0003_conversations.py`,
  `io_assistant/conversation/__init__.py`, `io_assistant/conversation/store.py`,
  `io_assistant/conversation/context.py`
- Modify: `io_assistant/db/models.py`
- Test: `tests/test_conversation_store.py`, `tests/test_conversation_context.py`

**Interfaces:**
- Consumes: `io_assistant.db.base` (`make_engine`, `make_session_factory`).
- Produces:
  - ORM `Conversation(id, title, started_at, last_at)` and
    `Message(id, conversation_id, role, text, kind, intent, source,
    utterance_id, audio_ms, created_at)` in `db/models.py`, matching the spec §3.1
    DDL. FK `messages.conversation_id → conversations.id ON DELETE CASCADE`,
    `messages.utterance_id → utterances.id ON DELETE SET NULL`. Indexes
    `ix_messages_conversation_id_created_at`, `ix_conversations_last_at`.
  - `io_assistant.conversation.context`:
    - `Turn` (dataclass): `role: str`, `text: str`.
    - `format_context(turns: list[Turn], *, max_chars: int = 1400) -> str` —
      renders `"you: <text>"` / `"io: <text>"` lines oldest-first; if the whole
      block exceeds `max_chars`, drop whole turns from the **front** until it
      fits. Returns `""` for an empty list.
  - `io_assistant.conversation.store.ConversationStore(session_factory)`:
    - `create(self) -> int`
    - `active_id(self) -> int | None` — highest `last_at`
    - `ensure_active(self) -> int` — `active_id()` or `create()`
    - `append(self, conv_id, role, text, *, kind=None, intent=None,
      source="text", utterance_id=None, audio_ms=None) -> int` — insert, bump
      `conversations.last_at = now()`, and set `title` (first 80 chars of `text`)
      when `role == "user"` and `title is None`. Commits.
    - `recent_turns(self, conv_id, n=6) -> list[Turn]` — last `n` messages,
      oldest first.
    - `history(self, conv_id, *, before_id=None, limit=50) -> list[dict]` —
      messages newest first, `id < before_id` when given; each dict is
      `{id, role, text, kind, intent, source, created_at}` (ISO timestamp).
    - `list_conversations(self, limit=40) -> list[dict]` —
      `{id, title, last_at, message_count}` by `last_at` desc.

- [ ] **Step 1: Write the failing context test** — `tests/test_conversation_context.py`

```python
from io_assistant.conversation.context import Turn, format_context


def test_empty():
    assert format_context([]) == ""


def test_renders_oldest_first():
    out = format_context([Turn("user", "hi"), Turn("assistant", "hello"),
                          Turn("user", "what work do I have")])
    assert out.splitlines() == ["you: hi", "io: hello", "you: what work do I have"]


def test_drops_from_front_when_over_cap():
    turns = [Turn("user", "x" * 300) for _ in range(10)]
    out = format_context(turns, max_chars=700)
    assert len(out) <= 700
    assert out.endswith("x" * 300)  # newest kept
```

- [ ] **Step 2: Run it, watch it fail**

Run: `uv run pytest tests/test_conversation_context.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `io_assistant/conversation/__init__.py`** (empty) and
  `io_assistant/conversation/context.py`

```python
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Turn", "format_context"]


@dataclass
class Turn:
    role: str
    text: str


def format_context(turns: list[Turn], *, max_chars: int = 1400) -> str:
    lines = [
        f"{'you' if t.role == 'user' else 'io'}: {t.text.strip()}"
        for t in turns
    ]
    while lines and len("\n".join(lines)) > max_chars:
        lines.pop(0)
    return "\n".join(lines)
```

- [ ] **Step 4: Run it, watch it pass**

Run: `uv run pytest tests/test_conversation_context.py -q`
Expected: PASS.

- [ ] **Step 5: Add the ORM models** — `io_assistant/db/models.py`

Append (mirror the existing style, `BigInteger` PKs, `DateTime(timezone=True)`):

```python
class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_last_at", "last_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(12), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str | None] = mapped_column(String(16), nullable=True)
    intent: Mapped[str | None] = mapped_column(String(12), nullable=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="text")
    utterance_id: Mapped[int | None] = mapped_column(
        ForeignKey("utterances.id", ondelete="SET NULL"), nullable=True)
    audio_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
```

(`Integer` and `Index` are already imported in `models.py`; add if missing.)

- [ ] **Step 6: Write `0003_conversations.py`**

```python
"""conversations + messages

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("last_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_conversations_last_at", "conversations", ["last_at"])
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("conversation_id", sa.BigInteger(),
                  sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(12), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=True),
        sa.Column("intent", sa.String(12), nullable=True),
        sa.Column("source", sa.String(8), server_default="text", nullable=False),
        sa.Column("utterance_id", sa.BigInteger(),
                  sa.ForeignKey("utterances.id", ondelete="SET NULL"), nullable=True),
        sa.Column("audio_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_messages_conversation_id_created_at", "messages",
                    ["conversation_id", "created_at"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
```

- [ ] **Step 7: Implement `io_assistant/conversation/store.py`**

```python
from __future__ import annotations

from dataclasses import asdict

from sqlalchemy import func, select

from io_assistant.conversation.context import Turn
from io_assistant.db import models as m

__all__ = ["ConversationStore"]


class ConversationStore:
    def __init__(self, session_factory):
        self._sf = session_factory

    def create(self) -> int:
        with self._sf() as s:
            conv = m.Conversation()
            s.add(conv)
            s.commit()
            return conv.id

    def active_id(self) -> int | None:
        with self._sf() as s:
            return s.execute(
                select(m.Conversation.id).order_by(m.Conversation.last_at.desc()).limit(1)
            ).scalar_one_or_none()

    def ensure_active(self) -> int:
        return self.active_id() or self.create()

    def append(self, conv_id, role, text, *, kind=None, intent=None,
               source="text", utterance_id=None, audio_ms=None) -> int:
        with self._sf() as s:
            conv = s.get(m.Conversation, conv_id)
            if conv is None:
                raise ValueError(f"no conversation {conv_id}")
            msg = m.Message(conversation_id=conv_id, role=role, text=text,
                            kind=kind, intent=intent, source=source,
                            utterance_id=utterance_id, audio_ms=audio_ms)
            s.add(msg)
            conv.last_at = func.now()
            if role == "user" and conv.title is None:
                conv.title = text.strip()[:80]
            s.commit()
            return msg.id

    def recent_turns(self, conv_id, n: int = 6) -> list[Turn]:
        with self._sf() as s:
            rows = s.execute(
                select(m.Message.role, m.Message.text)
                .where(m.Message.conversation_id == conv_id)
                .order_by(m.Message.created_at.desc(), m.Message.id.desc())
                .limit(n)
            ).all()
        return [Turn(role=r, text=t) for r, t in reversed(rows)]

    def history(self, conv_id, *, before_id=None, limit: int = 50) -> list[dict]:
        with self._sf() as s:
            stmt = select(m.Message).where(m.Message.conversation_id == conv_id)
            if before_id is not None:
                stmt = stmt.where(m.Message.id < before_id)
            stmt = stmt.order_by(m.Message.id.desc()).limit(limit)
            rows = s.execute(stmt).scalars().all()
        return [
            {"id": r.id, "role": r.role, "text": r.text, "kind": r.kind,
             "intent": r.intent, "source": r.source,
             "created_at": r.created_at.isoformat()}
            for r in rows
        ]

    def list_conversations(self, limit: int = 40) -> list[dict]:
        with self._sf() as s:
            rows = s.execute(
                select(
                    m.Conversation.id, m.Conversation.title, m.Conversation.last_at,
                    func.count(m.Message.id),
                )
                .outerjoin(m.Message, m.Message.conversation_id == m.Conversation.id)
                .group_by(m.Conversation.id)
                .order_by(m.Conversation.last_at.desc())
                .limit(limit)
            ).all()
        return [
            {"id": i, "title": t, "last_at": la.isoformat(), "message_count": c}
            for i, t, la, c in rows
        ]
```

- [ ] **Step 8: Write the failing store test** — `tests/test_conversation_store.py`

```python
from tests.conftest import requires_db
from io_assistant.conversation.store import ConversationStore


@requires_db
def test_conversation_lifecycle(db):
    store = ConversationStore(lambda: db)
    cid = store.ensure_active()
    assert store.active_id() == cid

    store.append(cid, "user", "what work do I have today?")
    store.append(cid, "assistant", "Two tasks are open.", kind="answer", intent="query")
    store.append(cid, "user", "and Sana?")

    turns = store.recent_turns(cid, n=6)
    assert [t.role for t in turns] == ["user", "assistant", "user"]
    assert turns[0].text == "what work do I have today?"

    hist = store.history(cid)
    assert hist[0]["text"] == "and Sana?"  # newest first
    assert len(hist) == 3

    convs = store.list_conversations()
    assert convs[0]["id"] == cid
    assert convs[0]["title"] == "what work do I have today?"
    assert convs[0]["message_count"] == 3
```

`db` here is the function-scoped session; `lambda: db` used as the factory works
because `ConversationStore` opens it as a context manager (`with self._sf() as
s`) — the `Session` context manager closes but the fixture's rolled-back
transaction keeps every commit contained (Plan-1 cleanup Task 3 guard).

- [ ] **Step 9: Rebuild the test schema and run**

The `engine` fixture runs `alembic upgrade head`, so it picks up `0003`.
Run: `uv run pytest tests/test_conversation_store.py -q`
Expected: PASS.
Then `uv run pytest -q` — no regressions.

- [ ] **Step 10: Commit**

```bash
git add io_assistant/db/ io_assistant/conversation/ tests/test_conversation_store.py tests/test_conversation_context.py
git commit -m "feat: 0003 conversations/messages + ConversationStore + context formatter"
```

---

## Task 2: `Card` domain types + `build_fact_list` for `acknowledge`

**Files:**
- Modify: `io_assistant/models_domain.py`
- Create: `io_assistant/extract/acknowledge.py`
- Test: `tests/test_backend_context.py` (partial — the fact list), `tests/test_query_respond.py` (unaffected)

**Interfaces:**
- Produces:
  - `io_assistant.models_domain`:
    - `EntityRef` (pydantic): `etype: Literal["person","place","item","occasion"]`,
      `id: int`, `name: str`.
    - `RecordCard` (pydantic): `type: Literal["record"] = "record"`,
      `record_id: int`, `kind: str`, `domain: str | None`, `title: str`,
      `entities: list[EntityRef] = []`, `when: datetime | None = None`,
      `due: datetime | None = None`, `status: str | None = None`.
    - `TaskListItem`: `record_id: int`, `title: str`, `status: str | None`,
      `due: datetime | None = None`.
    - `TaskListCard`: `type: Literal["tasklist"] = "tasklist"`, `items: list[TaskListItem]`.
    - `SourcesCard`: `type: Literal["sources"] = "sources"`, `record_ids: list[int]`,
      `count: int`, `labels: list[str] = []`.
    - `Card = RecordCard | TaskListCard | SourcesCard` (a `Union`).
  - `io_assistant.extract.acknowledge.build_fact_list(session, persist_result, extraction, now) -> str`
    — a compact plain-text summary of what `persist_store` **actually wrote**,
    for the `acknowledge` prompt: one line per record
    (`kind "title" — with <people>; at <place>; occasion <occasion>; when <ISO date>`),
    reading the resolved names from the DB via `persist_result.record_ids`. No
    model call.

- [ ] **Step 1: Write the failing test** — `tests/test_backend_context.py`

```python
import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.extract.acknowledge import build_fact_list
from io_assistant.models_domain import ExtractionResult, ExtractedRecord

NOW = dt.datetime(2026, 9, 8, 20, 0, tzinfo=dt.timezone.utc)


@requires_db
def test_build_fact_list_from_written_rows(db):
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    p = m.Person(canonical_name="Nafay", aliases=[]); db.add(p); db.flush()
    r = m.Record(kind="event", domain="social", title="dinner with Nafay",
                 occurred_at=NOW, attributes={}, source_utterance_id=u.id)
    db.add(r); db.flush()
    db.add(m.RecordPerson(record_id=r.id, person_id=p.id)); db.flush()

    class PR:  # stand-in for PersistResult
        record_ids = [r.id]

    out = build_fact_list(db, PR(), ExtractionResult(records=[
        ExtractedRecord(kind="event", title="dinner with Nafay", confidence=0.9)]), NOW)
    assert 'event "dinner with Nafay"' in out
    assert "Nafay" in out and "2026-09-08" in out
```

- [ ] **Step 2: Run, watch it fail**

Run: `uv run pytest tests/test_backend_context.py::test_build_fact_list_from_written_rows -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement the `Card` types** in `io_assistant/models_domain.py`

Add the pydantic models from the Interfaces block. Keep them near the other
`Extracted*` models; export nothing special (they're imported by name).

- [ ] **Step 4: Implement `io_assistant/extract/acknowledge.py`**

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from io_assistant.db import models as m

__all__ = ["build_fact_list"]

_LINKS = (
    ("with", m.RecordPerson, m.Person, m.RecordPerson.person_id, m.Person.id, m.Person.canonical_name),
    ("at", m.RecordPlace, m.Place, m.RecordPlace.place_id, m.Place.id, m.Place.name),
    ("item", m.RecordItem, m.Item, m.RecordItem.item_id, m.Item.id, m.Item.name),
    ("occasion", m.RecordOccasion, m.Occasion, m.RecordOccasion.occasion_id, m.Occasion.id, m.Occasion.name),
)


def build_fact_list(session, persist_result, extraction, now: datetime) -> str:
    lines: list[str] = []
    for rid in getattr(persist_result, "record_ids", []):
        rec = session.get(m.Record, rid)
        if rec is None:
            continue
        parts = [f'{rec.kind} "{rec.title}"']
        for word, link, _model, link_eid, ent_id, ent_name in _LINKS:
            names = [
                n for (n,) in session.execute(
                    select(ent_name).join(link, link_eid == ent_id)
                    .where(getattr(link, "record_id") == rid)
                ).all()
            ]
            if names:
                parts.append(f"{word} {', '.join(names)}")
        when = rec.occurred_at or rec.due_at
        if when is not None:
            parts.append(f"when {when.date().isoformat()}")
        if rec.status:
            parts.append(f"status {rec.status}")
        lines.append("; ".join(parts))
    return "\n".join(lines) or "nothing recorded"
```

- [ ] **Step 5: Run, watch it pass**

Run: `uv run pytest tests/test_backend_context.py::test_build_fact_list_from_written_rows -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/models_domain.py io_assistant/extract/acknowledge.py tests/test_backend_context.py
git commit -m "feat: Card domain types + build_fact_list() for acknowledge"
```

---

## Task 3: `Backend` context params + `acknowledge()`

**Files:**
- Modify: `io_assistant/backend/interface.py`, `local.py`, `anthropic_backend.py`,
  `hybrid.py`, `tests/conftest.py` (`FakeBackend`)
- Create: `io_assistant/prompts/acknowledge.txt`
- Modify: `io_assistant/prompts/route.txt`, `plan.txt`, `respond.txt`
- Test: `tests/test_backend_context.py`, `tests/test_backend_local.py`,
  `tests/test_backend_anthropic.py`

**Interfaces:**
- Produces:
  - `Backend` protocol (`interface.py`):
    ```python
    def route(self, utterance: str, *, context: str | None = None) -> Intent: ...
    def plan(self, question: str, now: datetime, *, context: str | None = None) -> dict: ...
    def phrase(self, question: str, rows: list[dict], shape: AnswerShape,
               *, context: str | None = None) -> str: ...
    def acknowledge(self, facts: str, *, context: str | None = None) -> str: ...
    ```
    `extract` is unchanged. `context` is the `format_context` string or `None`.
  - Each prompt gains a `{context}` slot filled by a shared helper
    `render_context(context: str | None) -> str` (in `interface.py`): returns
    `""` when falsy, else `f"Recent conversation:\n{context}\n\n"`.
  - `acknowledge.txt` — instructs: "You just saved the following to the user's
    memory. Reply in ONE natural sentence confirming it, the way a calm personal
    assistant would. Do not add facts, do not ask a question, do not list. {context}
    Saved:\n{facts}". `acknowledge` returns the model's line, stripped.
  - `FakeBackend`: stores `self.last_context` (the last non-None context seen on
    any method); `set_ack(s)` + `acknowledge()` returns it; `route`/`plan`/`phrase`
    accept and record `context`.
  - `HybridBackend`: `route(context=…)` → local; `plan`/`phrase`/`acknowledge`
    (with `context`) → cloud.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_backend_context.py`

```python
def test_fake_backend_records_context(fake_backend):
    fake_backend.set_intent("query")
    fake_backend.route("and last week?", context="you: where did I see Nafay\nio: Tuesday")
    assert "Nafay" in fake_backend.last_context


def test_fake_backend_acknowledge(fake_backend):
    fake_backend.set_ack("Logged dinner with Nafay at Arcadian.")
    assert fake_backend.acknowledge("event \"dinner\"; with Nafay") == "Logged dinner with Nafay at Arcadian."
```

`tests/test_backend_local.py` (append):

```python
def test_local_route_includes_context(config, monkeypatch):
    seen = _patch_chat(monkeypatch, "QUERY")
    from io_assistant.backend.local import LocalBackend
    LocalBackend(config).route("and Sana?", context="you: what about Nafay\nio: ok")
    body = seen.last  # the FakeClient records the last json body
    user_msg = body["messages"][-1]["content"]
    assert "Recent conversation" in user_msg and "Nafay" in user_msg


def test_local_acknowledge_returns_line(config, monkeypatch):
    _patch_chat(monkeypatch, "Logged your dinner with Nafay.")
    from io_assistant.backend.local import LocalBackend
    assert LocalBackend(config).acknowledge('event "dinner"; with Nafay') == "Logged your dinner with Nafay."
```

- [ ] **Step 2: Run, watch them fail**

Run: `uv run pytest tests/test_backend_context.py tests/test_backend_local.py -q`
Expected: FAIL — `TypeError` (unexpected `context=`), no `acknowledge`.

- [ ] **Step 3: Update `interface.py`**

```python
def render_context(context: str | None) -> str:
    return f"Recent conversation:\n{context}\n\n" if context else ""
```
Update the `Backend` Protocol method signatures per the Interfaces block; add
`acknowledge`.

- [ ] **Step 4: Update the prompt files**

- `route.txt`: put `{context}` immediately before `Utterance:` — the recent
  turns help classify "yeah" / "and Sana?".
- `plan.txt`: `{context}` before `Question (assume "now" is {now}):`.
- `respond.txt`: `{context}` before `Question:` — lets the phraser refer back
  ("that same evening", "as I mentioned").
- `acknowledge.txt`: new (text in the Interfaces block).
- Every backend renders these with `.format(context=render_context(context), …)`.

- [ ] **Step 5: Implement the backends**

`local.py` — thread `context` through `route`/`plan`/`phrase` `.format(...)`
calls; add:
```python
    def acknowledge(self, facts: str, *, context: str | None = None) -> str:
        return self._chat(
            "You confirm saved items as a calm personal assistant.",
            _load_prompt("acknowledge.txt").format(
                context=render_context(context), facts=facts),
            json_mode=False,
        ).strip()
```
`anthropic_backend.py` — same shape, `max_tokens=120` for `acknowledge`.
`hybrid.py` — `route` local (with context), `plan`/`phrase`/`acknowledge` cloud.

`conftest.FakeBackend`:
```python
    def __init__(self):
        ...
        self._ack = ""
        self.last_context: str | None = None
    def _ctx(self, c):
        if c: self.last_context = c
    def set_ack(self, s): self._ack = s
    def route(self, utterance, *, context=None):
        self._ctx(context); self.calls.append("route"); return self._intent
    def plan(self, question, now, *, context=None):
        self._ctx(context); self.calls.append("plan"); return self._plan
    def phrase(self, question, rows, shape, *, context=None):
        self._ctx(context); self.calls.append("phrase"); return self._answer
    def acknowledge(self, facts, *, context=None):
        self._ctx(context); self.calls.append("acknowledge"); return self._ack
```

- [ ] **Step 6: Run the touched tests**

Run: `uv run pytest tests/test_backend_context.py tests/test_backend_local.py tests/test_backend_anthropic.py tests/test_backend_interface.py tests/test_router.py tests/test_query_planner.py tests/test_query_respond.py -q`
Expected: PASS. Fix any call site that passed positional args.

- [ ] **Step 7: Commit**

```bash
git add io_assistant/backend/ io_assistant/prompts/ tests/
git commit -m "feat: Backend context= on route/plan/phrase + acknowledge()"
```

---

## Task 4: `Orchestrator` — history threading, `acknowledge`, cards

**Files:**
- Modify: `io_assistant/orchestrator.py`, `io_assistant/route/router.py`,
  `io_assistant/query/planner.py`, `io_assistant/query/pipeline.py`,
  `io_assistant/query/respond.py`, `io_assistant/query/rank.py` (expose card data)
- Create: `io_assistant/orchestrator_cards.py` (card builders)
- Test: `tests/test_orchestrator_conversation.py`

**Interfaces:**
- Produces:
  - `Router.classify(utterance, *, context=None)`, `Planner.run(question, now, *,
    context=None)`, `Responder.run(question, rows, shape, *, context=None)`,
    `QueryPipeline.answer(session, question, now, *, context=None) -> QueryAnswer`
    — all thread `context` to the backend. `QueryAnswer` gains
    `source_record_ids: list[int]` and `list_records: list[RecordRef]` (the
    ranked rows that are records, projected to `{record_id, kind, domain, title,
    status, when, due, entity_ids}` — enough to build cards without re-querying).
  - `io_assistant.orchestrator_cards`:
    - `store_cards(session, persist_result) -> list[Card]` — one `RecordCard` per
      `persist_result.record_ids`, `entities` filled from the link tables.
    - `query_cards(session, answer: QueryAnswer) -> list[Card]` — a `SourcesCard`
      (`record_ids = answer.source_record_ids`, `labels = ["memory"]`) and, when
      `answer.list_records` are all actionable (`kind in {"task","chore"}` or
      have a `due`), a `TaskListCard`.
  - `HandleResult` gains `cards: list[Card] = []` and
    `intent_kind: str = "unknown"` (`answer`|`ack`|`gate`|`unknown`|`error`).
  - `Orchestrator.handle(text, *, source="text", captured_at=None,
    confirmed=False, pending=None, history: str | None = None) -> HandleResult`:
    - router/planner/phraser calls pass `context=history`.
    - STORE success: `facts = build_fact_list(session, result, extraction, now)`;
      `message = _acknowledge_or_fallback(self._backend, facts, history, result, session)`
      — try `backend.acknowledge`, on `Exception` fall back to
      `"Stored: " + _summarize(session, result)`. `cards = store_cards(...)`,
      `intent_kind = "ack"`.
    - QUERY: `cards = query_cards(...)`, `intent_kind = "answer"`.
    - gate → `intent_kind = "gate"`; unknown → `"unknown"`; extraction-failed or
      swallowed `PersistError` → `"error"`.

- [ ] **Step 1: Write the failing test** — `tests/test_orchestrator_conversation.py`

```python
import datetime as dt

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedRecord)
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 8, 20, 0, tzinfo=dt.timezone.utc)


def _stub_embedder(monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())


@requires_db
def test_store_uses_acknowledge_and_builds_cards(db, config, fake_backend, monkeypatch):
    _stub_embedder(monkeypatch)
    fake_backend.set_intent("store")
    fake_backend.set_ack("Logged dinner with Nafay at Arcadian this evening.")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        records=[ExtractedRecord(kind="event", domain="social",
                                 title="dinner with Nafay", when_phrase="today",
                                 people=["Nafay"], places=["Arcadian"], confidence=0.9)]))
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("dinner with Nafay at Arcadian",
                   history="you: hi\nio: hello", captured_at=NOW)

    assert res.message == "Logged dinner with Nafay at Arcadian this evening."
    assert res.intent_kind == "ack"
    assert "hi" in fake_backend.last_context               # history threaded
    assert [c.type for c in res.cards] == ["record"]
    card = res.cards[0]
    assert card.title == "dinner with Nafay"
    assert {e.name for e in card.entities} == {"Nafay", "Arcadian"}


@requires_db
def test_query_builds_sources_card(db, config, fake_backend, monkeypatch):
    _stub_embedder(monkeypatch)
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    db.add(m.Record(kind="task", domain="job", title="finish the deck", status="open",
                    due_at=NOW, attributes={}, source_utterance_id=u.id)); db.flush()
    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [{"target_type": "record",
                          "kind_filter": ["task"], "status_filter": ["open"]}],
                          "answer_shape": "markdown"})
    fake_backend.set_answer("- finish the deck")
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("what tasks do I have?", history="", captured_at=NOW)
    types = {c.type for c in res.cards}
    assert "sources" in types
```

- [ ] **Step 2: Run, watch it fail**

Run: `uv run pytest tests/test_orchestrator_conversation.py -q`
Expected: FAIL — `handle()` has no `history`, no `intent_kind`, no `cards`.

- [ ] **Step 3: Thread `context` through the query layer**

`router.py`: `classify(self, utterance, *, context=None)` → `self._backend.route(utterance, context=context)`.
`planner.py`: `run(self, question, now, *, context=None)` → `self._backend.plan(question, now, context=context)`.
`respond.py`: `Responder.run(self, question, rows, shape, *, context=None)` → `self._backend.phrase(question, rows_to_json(rows), shape, context=context)`.
`pipeline.py`: `answer(self, session, question, now, *, context=None)` passes `context` to `Planner.run` and `Responder.run`; after ranking, set
`ans.source_record_ids = [r.obj.id for r in final if r.target_type == "record"]`
and `ans.list_records = [_project(r) for r in final if r.target_type == "record"]`.
`rank.py` / a small helper: `_project(ranked_row) -> RecordRef` reads
`kind/domain/title/status/occurred_at/due_at` off the ORM obj and the linked
entity ids via the link tables (one `IN` query for all records in `final`).

- [ ] **Step 4: Implement `io_assistant/orchestrator_cards.py`**

```python
from __future__ import annotations

from sqlalchemy import select

from io_assistant.db import models as m
from io_assistant.models_domain import (
    Card, EntityRef, RecordCard, SourcesCard, TaskListCard, TaskListItem,
)

_ETYPES = (
    ("person", m.RecordPerson, m.RecordPerson.person_id, m.Person, m.Person.canonical_name),
    ("place", m.RecordPlace, m.RecordPlace.place_id, m.Place, m.Place.name),
    ("item", m.RecordItem, m.RecordItem.item_id, m.Item, m.Item.name),
    ("occasion", m.RecordOccasion, m.RecordOccasion.occasion_id, m.Occasion, m.Occasion.name),
)


def _entities_for(session, record_id: int) -> list[EntityRef]:
    out: list[EntityRef] = []
    for etype, link, link_eid, model, name_col in _ETYPES:
        rows = session.execute(
            select(model.id, name_col).join(link, link_eid == model.id)
            .where(link.record_id == record_id)
        ).all()
        out += [EntityRef(etype=etype, id=i, name=n) for i, n in rows]
    return out


def store_cards(session, persist_result) -> list[Card]:
    cards: list[Card] = []
    for rid in getattr(persist_result, "record_ids", []):
        rec = session.get(m.Record, rid)
        if rec is None:
            continue
        cards.append(RecordCard(
            record_id=rec.id, kind=rec.kind, domain=rec.domain, title=rec.title,
            entities=_entities_for(session, rec.id),
            when=rec.occurred_at, due=rec.due_at, status=rec.status,
        ))
    return cards


def query_cards(session, answer) -> list[Card]:
    cards: list[Card] = []
    if answer.source_record_ids:
        cards.append(SourcesCard(
            record_ids=list(answer.source_record_ids),
            count=len(answer.source_record_ids), labels=["memory"],
        ))
    lr = getattr(answer, "list_records", [])
    if lr and all(r.kind in ("task", "chore") or r.due is not None for r in lr):
        cards.append(TaskListCard(items=[
            TaskListItem(record_id=r.record_id, title=r.title, status=r.status, due=r.due)
            for r in lr
        ]))
    return cards
```

- [ ] **Step 5: Update `orchestrator.py`**

Add `cards` + `intent_kind` to `HandleResult`. In `_handle_in_session`, pass
`context=history` to `self._router.classify`. In the query branch, pass
`context=history` to `self._query.answer` and set
`result.cards = query_cards(session, answer)`, `result.intent_kind = "answer"`.
In `_store`, on success replace the `_summarize` message with:
```python
from io_assistant.extract.acknowledge import build_fact_list
from io_assistant.orchestrator_cards import store_cards
...
        facts = build_fact_list(session, result, extraction, now)
        try:
            message = self._backend.acknowledge(facts, context=history)
        except Exception:
            message = "Stored: " + self._summarize(session, result)
        cards = store_cards(session, result)
        return HandleResult("store", result, message, cards=cards, intent_kind="ack")
```
Pass `history` down from `handle` → `_handle_in_session` → `_store`. Gate branch
sets `intent_kind="gate"`; extraction-failed and the swallowed `PersistError`
branch set `intent_kind="error"`; unknown sets `"unknown"`.

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_orchestrator_conversation.py tests/test_orchestrator_store.py tests/test_orchestrator_query.py tests/test_e2e_store.py tests/test_e2e_query.py -q`
Expected: PASS. The existing orchestrator tests still pass — `history` defaults
to `None`, and STORE messages that were `"Stored: …"` are now the
`FakeBackend` ack string (`""` unless `set_ack`) — **update those assertions**:
where a test asserted `"Stored:" in res.message` or a summarized string, either
call `fake_backend.set_ack("Stored: …")` or assert on `res.cards` / `res.stored`
instead.

- [ ] **Step 7: Full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add io_assistant/ tests/
git commit -m "feat: Orchestrator threads conversation history, acknowledges naturally, returns cards"
```

---

## Task 5: `ConversationStore` in the service + `TurnResponse`

**Files:**
- Modify: `io_assistant/service/schemas.py`, `io_assistant/service/app.py`
- Test: `tests/test_service_conversation.py`, `tests/test_service_utterance.py`
  (update), `tests/test_service_ws.py` (update), `tests/test_service_e2e.py` (update)

**Interfaces:**
- Produces:
  - `schemas.py`:
    - `TurnResponse` (pydantic): `kind: str`, `intent: str`, `text: str`,
      `shape: str = "text"`, `cards: list[dict] = []`, `pending_token: str | None
      = None`, `conversation_id: int`, `message_id: int`, `audio_b64: str | None
      = None`. (`cards` as `list[dict]` — the pydantic `Card` union is dumped with
      `model_dump()`.)
    - `UtteranceIn` gains `conversation_id: int | None = None`.
    - `ConversationSummary`, `MessageOut`, `NewConversationOut` DTOs.
  - `app.py`:
    - `create_app` builds `app.state.conversations = ConversationStore(factory)`
      where `factory` is a real `sessionmaker` on `app.state.engine`. In tests
      that inject `orchestrator=`, also inject `conversations=` (a store bound to
      the test session) — add a `conversations=None` kwarg to `create_app`.
    - `_run(body) -> TurnResponse` now:
      ```
      store = app.state.conversations
      conv_id = body.conversation_id or store.ensure_active()
      store.append(conv_id, "user", text, source=body.source)
      history = format_context(store.recent_turns(conv_id))
      result = orchestrator.handle(text, source=body.source, history=history, pending=pending)
      msg_id = store.append(conv_id, "assistant", result.message,
                            kind=result.intent_kind, intent=result.intent, source=body.source)
      return TurnResponse(kind=result.intent_kind, intent=result.intent,
                          text=result.message, shape=<from result>, 
                          cards=[c.model_dump(mode="json") for c in result.cards],
                          pending_token=token, conversation_id=conv_id, message_id=msg_id)
      ```
      (`shape` — plumb `QueryAnswer.shape` onto `HandleResult` as `shape: str =
      "text"`; STORE/ack is `"text"`.)
    - `POST /utterance` and `WS /ws` both return `TurnResponse` (WS wraps it
      `{"type": "answer", **turn.model_dump()}`).
    - `GET /conversation?id=&before=` → `{conversation_id, messages: [MessageOut]}`
      (via `store.history`); `id` defaults to `active_id()`.
    - `POST /conversation` → `{conversation_id}` (`store.create()`).
    - `GET /conversations` → `[ConversationSummary]` (`store.list_conversations()`).

- [ ] **Step 1: Write the failing test** — `tests/test_service_conversation.py`

```python
from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.conversation.store import ConversationStore
from io_assistant.service.app import create_app
from io_assistant.models_domain import ExtractionResult, ExtractedRecord
from io_assistant.db import models as m


def _stub(monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())


@requires_db
def test_two_turns_persist_and_follow_up_has_context(config, fake_backend, db, monkeypatch):
    _stub(monkeypatch)
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    store = ConversationStore(lambda: db)
    app = create_app(config, orchestrator=o, engine=db.get_bind(), conversations=store)

    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [], "answer_shape": "text"})
    with TestClient(app) as c:
        r1 = c.post("/utterance", json={"text": "where did I see Nafay?"})
        cid = r1.json()["conversation_id"]
        assert r1.json()["kind"] in ("answer", "unknown")
        r2 = c.post("/utterance", json={"text": "and last week?", "conversation_id": cid})

    # the second turn's route/plan saw the first exchange
    assert "Nafay" in (fake_backend.last_context or "")
    # four messages persisted (2 user, 2 assistant)
    assert db.query(m.Message).filter_by(conversation_id=cid).count() == 4

    with TestClient(app) as c:
        hist = c.get("/conversation", params={"id": cid}).json()["messages"]
    assert hist[0]["text"] == "and last week?"
    assert len(hist) == 4
```

- [ ] **Step 2: Run, watch it fail**

Run: `uv run pytest tests/test_service_conversation.py -q`
Expected: FAIL — no `conversations=` kwarg, `/utterance` returns `UtteranceOut`
not `TurnResponse`.

- [ ] **Step 3: Implement** per the Interfaces block. Keep `UtteranceOut`
  removed — replace all its uses with `TurnResponse`. Update
  `tests/test_service_utterance.py` / `_ws.py` / `_e2e.py` to read
  `body["text"]` / `body["kind"]` instead of `body["message"]` / `body["stored"]`
  (a store is now `kind == "ack"`; a gate is `kind == "gate"` with a
  `pending_token`).

- [ ] **Step 4: Run the service tests**

Run: `uv run pytest tests/test_service_conversation.py tests/test_service_utterance.py tests/test_service_ws.py tests/test_service_e2e.py tests/test_service_health.py -q`
Expected: PASS.

- [ ] **Step 5: Full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/service/ tests/
git commit -m "feat: service owns conversations; /utterance + /ws return TurnResponse; /conversation(s)"
```

---

## Task 6: `POST /voice` + `/voice/health` + lazy model cache

**Files:**
- Create: `io_assistant/service/voice.py`
- Modify: `io_assistant/service/schemas.py`, `io_assistant/service/app.py`
- Test: `tests/test_service_voice.py`

**Interfaces:**
- Produces:
  - `io_assistant.service.voice.VoiceModels(config)`:
    - `transcriber()` / `speaker()` — lazily build `WhisperTranscriber` /
      `PiperSpeaker`, cache on the instance, and re-raise their init errors as
      `VoiceUnavailable(reason: str)`.
    - `health() -> dict` — `{whisper, piper, voice, reason}`; probes
      `importlib.util.find_spec` for `faster_whisper`, and
      `config.voice.resolved_voice_path.exists()` for Piper, without loading.
  - `schemas.VoiceOut` — `TurnResponse` fields **plus** `transcript: str`,
    `transcript_confidence: float | None`.
  - `app.py`:
    - `app.state.voice = VoiceModels(config)` (or an injected fake in tests).
    - `POST /voice` — `UploadFile audio`, `Form conversation_id: int | None`,
      `Form speak: str = "1"`. Save to a temp `.wav`, `t =
      voice.transcriber().transcribe(path)`. If `not t.text.strip()` → `422`
      `{"detail": "no speech"}`. Else build `UtteranceIn(text=t.text,
      source="voice", conversation_id=…)`, call `_run`, then if `speak == "1"`:
      `audio = voice.speaker().synthesize(turn.text)` → `audio_b64 =
      base64.b64encode(audio)`. Return `VoiceOut`. On `VoiceUnavailable` →
      `503 {"detail": reason}`.
    - `GET /voice/health` → `voice.health()`.

- [ ] **Step 1: Write the failing test** — `tests/test_service_voice.py`

```python
import base64
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.conversation.store import ConversationStore
from io_assistant.service.app import create_app
from io_assistant.db import models as m

WAV = Path(__file__).parent / "fixtures" / "audio" / "hello.wav"


class FakeVoice:
    def __init__(self, text="buy milk"):
        self._t = text
    def transcriber(self):
        outer = self
        class T:
            def transcribe(self, p):
                from io_assistant.transcribe.interface import Transcript
                return Transcript(text=outer._t, confidence=0.9)
        return T()
    def speaker(self):
        class S:
            def synthesize(self, text): return b"RIFF0000WAVEfmt "
        return S()
    def health(self):
        return {"whisper": True, "piper": True, "voice": "test", "reason": None}


def _stub(monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())


@requires_db
def test_voice_turn_transcribes_answers_and_speaks(config, fake_backend, db, monkeypatch):
    _stub(monkeypatch)
    fake_backend.set_intent("store")
    fake_backend.set_ack("Noted.")
    from io_assistant.models_domain import ExtractionResult, ExtractedRecord
    fake_backend.set_extraction(ExtractionResult(records=[
        ExtractedRecord(kind="note", title="buy milk", confidence=0.9)]))
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind(),
                     conversations=ConversationStore(lambda: db), voice=FakeVoice())
    with TestClient(app) as c:
        r = c.post("/voice", files={"audio": ("a.wav", WAV.read_bytes(), "audio/wav")},
                   data={"speak": "1"})
    body = r.json()
    assert r.status_code == 200
    assert body["transcript"] == "buy milk"
    assert body["kind"] == "ack" and body["text"] == "Noted."
    assert base64.b64decode(body["audio_b64"])[:4] == b"RIFF"
    assert db.query(m.Message).filter_by(source="voice").count() == 2


@requires_db
def test_voice_health(config, fake_backend, db):
    app = create_app(config, orchestrator=Orchestrator(config, session_factory=lambda: db,
                     backend=fake_backend), engine=db.get_bind(),
                     conversations=ConversationStore(lambda: db), voice=FakeVoice())
    with TestClient(app) as c:
        h = c.get("/voice/health").json()
    assert h["whisper"] is True and "voice" in h
```

- [ ] **Step 2: Run, watch it fail**

Run: `uv run pytest tests/test_service_voice.py -q`
Expected: FAIL — no `/voice`, no `voice=` kwarg.

- [ ] **Step 3: Implement `io_assistant/service/voice.py`** and the routes per
  the Interfaces block. `python-multipart` is already pulled by FastAPI; if
  `uv run python -c "import multipart"` fails, `uv add python-multipart`.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_service_voice.py -q` → PASS.
Then `uv run pytest -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/service/ tests/test_service_voice.py pyproject.toml uv.lock
git commit -m "feat: POST /voice + /voice/health with lazy Whisper/Piper in the service"
```

---

## Task 7: Natural Piper — `prep_for_speech` + sentence-wise synthesis

**Files:**
- Create: `io_assistant/speak/speech_text.py`
- Modify: `io_assistant/speak/piper.py`, `io_assistant/config.py`, `config.toml`
- Test: `tests/test_speak_natural.py`, `tests/test_speak_piper.py` (update)

**Interfaces:**
- Produces:
  - `io_assistant.speak.speech_text`:
    - `prep_for_speech(s: str) -> str` — `flatten_markdown` first, then: expand
      `Dr.`/`Mr.`/`Mrs.`/`Ms.`/`St.`, weekday abbreviations (`Mon`–`Sun`),
      `Q<n>` → `Q <n>`, `HH:MM` → a spoken time, `£<n>`/`$<n>` → words, `—`/` - `
      → `, `, `(...)` → `, ... ,`. Deterministic, pure.
    - `split_sentences(s: str) -> list[str]` — split on `.?!` keeping the mark;
      also split very long clauses (> 180 chars) on `;`/`,`.
  - `config.VoiceConfig` gains `length_scale: float = 1.06`,
    `noise_scale: float = 0.667`, `noise_w_scale: float = 0.85`, and
    `tts_voice` default changes to `"en_US-hfc_female-medium"`.
  - `PiperSpeaker.synthesize(text)` — `prep_for_speech` → `split_sentences` →
    synthesize each sentence with a `SynthesisConfig(length_scale=…,
    noise_scale=…, noise_w_scale=…)` → concatenate the PCM with a silence gap
    (`~180 ms` after `.?!`, `~120 ms` after `,;`) → one WAV. Empty input →
    a 1-frame silent WAV (never raises for empty).

- [ ] **Step 1: Write the failing test** — `tests/test_speak_natural.py`

```python
from io_assistant.speak.speech_text import prep_for_speech, split_sentences


def test_prep_expands_and_pauses():
    out = prep_for_speech("**Dr. Smith** moved you to Thu 14:30 — bring the Q3 deck.")
    assert "Doctor Smith" in out
    assert "Thursday" in out
    assert "—" not in out
    assert "*" not in out


def test_split_sentences_keeps_marks():
    s = "Two things are open. Finish the deck, and call the dentist. That's it."
    assert split_sentences(s) == [
        "Two things are open.",
        "Finish the deck, and call the dentist.",
        "That's it.",
    ]
```

- [ ] **Step 2: Run, watch it fail** → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `speech_text.py`** and rewrite `PiperSpeaker.synthesize`
  per the Interfaces block. Concatenate WAVs by reading frames from each
  `wave` and writing one output `wave` at the shared rate; insert
  `int(rate * gap_s)` zero frames between.

- [ ] **Step 4: Update `config.py` / `config.toml` / the `config` fixture** with
  the new `[voice]` keys and the new default voice. Update
  `tests/conftest.py`'s `VoiceConfig()` (defaults suffice).

- [ ] **Step 5: Run**

Run: `uv run pytest tests/test_speak_natural.py tests/test_speak_piper.py tests/test_speak_text.py -q`
Expected: PASS (the `@pytest.mark.voice` real-synthesis test still skipped).

- [ ] **Step 6: Commit**

```bash
git add io_assistant/speak/ io_assistant/config.py config.toml tests/
git commit -m "feat: natural Piper — speech text prep + sentence-wise synthesis with pacing"
```

---

## Task 8: `io listen` → `POST /voice`

**Files:**
- Modify: `io_assistant/voice/loop.py`, `io_assistant/voice/client.py`,
  `io_assistant/cli.py`
- Test: `tests/test_voice_loop.py` (rewrite)

**Interfaces:**
- Produces:
  - `ServiceClient.send_voice(self, wav_bytes: bytes, *, conversation_id=None,
    speak=True) -> dict` — `POST /voice` multipart, returns the `VoiceOut` dict.
  - `VoiceLoop.handle_wav(wav_path)` — reads the file, calls
    `client.send_voice(...)`, prints `reply["text"]`, and if `reply["audio_b64"]`
    plays it (decode → `sounddevice`). Transcription and synthesis no longer
    happen in the loop — the server does both. `VoiceLoop.__init__` drops the
    `transcriber` / `speaker` params; keeps `client`.
  - `io listen` builds only `ServiceClient` + `VoiceLoop`, checks
    `GET /voice/health` (not just `/health`) and prints the `reason` if a model
    is missing.

- [ ] **Step 1: Rewrite `tests/test_voice_loop.py`**

```python
from io_assistant.voice.loop import VoiceLoop


class _Client:
    def __init__(self, reply): self.reply = reply; self.sent = []
    def send_voice(self, wav, *, conversation_id=None, speak=True):
        self.sent.append(wav); return self.reply


def test_handle_wav_prints_reply(config, tmp_path, capsys):
    wav = tmp_path / "x.wav"; wav.write_bytes(b"RIFF0000WAVEfmt ")
    client = _Client({"transcript": "what work do I have",
                      "text": "Two tasks are open.", "kind": "answer",
                      "audio_b64": None})
    VoiceLoop(config, client=client).handle_wav(str(wav))
    assert "Two tasks are open." in capsys.readouterr().out
    assert client.sent


def test_handle_wav_no_speech(config, tmp_path):
    wav = tmp_path / "x.wav"; wav.write_bytes(b"RIFF0000WAVEfmt ")
    class C:
        def send_voice(self, *a, **k): raise RuntimeError("422 no speech")
    # loop swallows a failed turn and returns without raising
    VoiceLoop(config, client=C()).handle_wav(str(wav))
```

- [ ] **Step 2: Run, watch it fail** → `VoiceLoop.__init__` still wants `transcriber`.

- [ ] **Step 3: Implement** the three changes. `handle_wav` wraps the
  `client.send_voice` call in `try/except Exception` → prints a one-line
  warning, returns.

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_voice_loop.py tests/test_cli_listen.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/voice/ io_assistant/cli.py tests/test_voice_loop.py
git commit -m "refactor: io listen is a thin client of POST /voice"
```

---

## Task 9: `GET /entity/{etype}/{id}` + `GET /standby`

**Files:**
- Create: `io_assistant/service/panels.py`
- Modify: `io_assistant/service/schemas.py`, `io_assistant/service/app.py`,
  `io_assistant/config.py` (`UiConfig`), `config.toml`
- Test: `tests/test_service_entity.py`, `tests/test_service_standby.py`

**Interfaces:**
- Produces:
  - `config.UiConfig` (pydantic): `name: str = ""` (empty → the OS user at read
    time), `fullscreen: bool = True`, `auto_speak: Literal["voice","always",
    "never"] = "voice"`, `typing_cps: int = 45`, `min_think_ms: int = 600`.
    `Config.ui: UiConfig = UiConfig()`.
  - `io_assistant.service.panels`:
    - `entity_panel(session, etype, entity_id) -> dict | None` — resolves the
      table from `etype`; returns `{etype, id, name, subtitle, facts: [{label,
      text, record_ids}], confidence, sourced_from}`. `facts` = the entity's
      linked records, newest first (cap 6), each `label` from
      `kind`/`domain`, `text` from `title` (+ `body` when present),
      `record_ids=[record.id]`. `subtitle` = `"<ROLE-ish> · <N> NOTES"` where
      ROLE-ish is `place.type` / `item.category` / `"PERSON"` / `"OCCASION"`.
      `confidence` = mean cosine similarity of those records' embeddings to the
      entity embedding (0.0 when no embeddings); `sourced_from` = distinct record
      count.
    - `standby_panel(session, config, recall_ms: int) -> dict` — `{greeting_name,
      stats: {memories, recall_ms, clock}, chips: [{icon, text, record_id}]}`.
      `greeting_name` = `config.ui.name or os.environ.get("USERNAME") or
      os.environ.get("USER") or "there"`. `memories` = `count(records)`.
      `chips`: (1) count of `task`/`chore` records with `status='open'` and a
      `due_at` today → `"N tasks today"`; (2) nearest future `occasion` with a
      `date` → `"<name> in <n> days"`; (3) nearest future `record` with a
      `due_at` → `"<title>, <weekday> <HH:MM>"`. Omit a chip when its query is
      empty.
  - `app.py`: `GET /entity/{etype}/{entity_id}` → `entity_panel(...)` or `404`;
    `GET /standby` → `standby_panel(session, config, app.state.recall_ms)`.
    `app.state.recall_ms` is a rolling mean updated in `_run` after a QUERY turn
    (`0` initially).

- [ ] **Step 1: Write the failing tests**

`tests/test_service_entity.py`:
```python
import datetime as dt
from fastapi.testclient import TestClient
from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.conversation.store import ConversationStore
from io_assistant.service.app import create_app
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)


@requires_db
def test_entity_panel(config, fake_backend, db):
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    p = m.Person(canonical_name="Priya", aliases=[]); db.add(p); db.flush()
    for i, title in enumerate(["started a ceramics class", "allergic to lilies"]):
        r = m.Record(kind="note", domain="social", title=title, attributes={},
                     occurred_at=NOW - dt.timedelta(days=i), source_utterance_id=u.id)
        db.add(r); db.flush()
        db.add(m.RecordPerson(record_id=r.id, person_id=p.id)); db.flush()

    app = create_app(config, orchestrator=Orchestrator(config, session_factory=lambda: db,
                     backend=fake_backend), engine=db.get_bind(),
                     conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        panel = c.get(f"/entity/person/{p.id}").json()
    assert panel["name"] == "Priya"
    assert len(panel["facts"]) == 2
    assert panel["facts"][0]["record_ids"]
    assert 0.0 <= panel["confidence"] <= 1.0
    assert panel["sourced_from"] == 2
```

`tests/test_service_standby.py`:
```python
import datetime as dt
from fastapi.testclient import TestClient
from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.conversation.store import ConversationStore
from io_assistant.service.app import create_app
from io_assistant.db import models as m

NOW = dt.datetime.now(dt.timezone.utc)


@requires_db
def test_standby_panel(config, fake_backend, db):
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    db.add(m.Record(kind="task", domain="job", title="finish deck", status="open",
                    due_at=NOW, attributes={}, source_utterance_id=u.id))
    db.add(m.Occasion(name="Priya's birthday", date=(NOW + dt.timedelta(days=11)).date()))
    db.flush()
    app = create_app(config, orchestrator=Orchestrator(config, session_factory=lambda: db,
                     backend=fake_backend), engine=db.get_bind(),
                     conversations=ConversationStore(lambda: db))
    with TestClient(app) as c:
        sb = c.get("/standby").json()
    assert sb["stats"]["memories"] >= 1
    texts = " ".join(ch["text"] for ch in sb["chips"])
    assert "task" in texts and "Priya" in texts
```

- [ ] **Step 2: Run, watch them fail** → no routes.

- [ ] **Step 3: Implement** `config.UiConfig`, `panels.py`, and the two routes.

- [ ] **Step 4: Run** those two files, then `uv run pytest -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/service/ io_assistant/config.py config.toml tests/
git commit -m "feat: GET /entity/{etype}/{id} (Memory Inspector) and GET /standby"
```

---

## Task 10: docs + state

**Files:**
- Modify: `.claude/knowledge/desktop-app.md`, `.claude/knowledge/model-backends.md`,
  `.claude/knowledge/architecture.md`, `.claude/state/*`
- Test: none.

- [ ] **Step 1: `desktop-app.md`** — add the conversation layer (`conversation/`
  store + `format_context`, `messages`/`conversations`, the per-turn flow),
  `TurnResponse` + `cards`, `POST /voice` + `/voice/health` + `VoiceModels`,
  `/conversation(s)`, `/entity/{…}`, `/standby`. Note the CLI still uses
  `history=None`.
- [ ] **Step 2: `model-backends.md`** — the `context=` param and `acknowledge()`;
  the LLM-boundary note that `acknowledge` only restates written facts.
- [ ] **Step 3: `architecture.md`** — one line: the service holds conversation
  state; the Orchestrator does not.
- [ ] **Step 4: Full suite + local-first guard**

Run: `uv run pytest -q` — PASS.
Confirm `tests/test_e2e_store.py` socket guard passes.
- [ ] **Step 5: Update `.claude/state/`** — move Plan 5 to `completed.md` (dated),
  note Plan 6 (Nocturne client) is next and the deferred backlog (1d task
  runner, external-source provenance, entity-file browser, `/ws` streaming,
  Kokoro).
- [ ] **Step 6: Commit**

```bash
git add .claude/
git commit -m "docs: conversation layer, /voice, panels; Plan 5 complete"
```

---

## Self-Review

**Spec coverage (Phase 1.5 §3–6):**
- §3.1 schema → Task 1 (`0003`). §3.2 store + context → Task 1. §3.3 Backend
  context + `acknowledge` → Task 3 (+ Task 2 `build_fact_list`). §3.4 Orchestrator
  history + cards + `intent_kind` → Task 4. §3.5 service wiring + `/conversation(s)`
  → Task 5.
- §4 `POST /voice` + `/voice/health` + lazy models → Task 6. §4 `io listen`
  refactor → Task 8. §4.1 natural Piper → Task 7.
- §5 `TurnResponse` + `Card` → Task 2 (types) + Task 4 (builders) + Task 5 (wire).
- §6.1 `GET /entity/…` → Task 9. §6.2 `GET /standby` → Task 9. §7.5 `[ui]` config
  → Task 9.

**LLM-boundary check:** `acknowledge` receives only `build_fact_list` output
(rows `persist_store` wrote) + the read-only context string; it returns prose.
`context` on `route`/`plan`/`phrase` is a string the model reads, never a
decision it makes — the plan/rows still flow through `ground_plan` /
`compile_structured` / `rank`. No task lets a model output reach SQL or storage
un-clamped.

**Local-first check:** `/voice` uses local Whisper/Piper; the service binds
127.0.0.1; no new outbound host. Task 10 Step 4 re-runs the socket guard.

**Placeholder scan:** none — every step has literal code or a runnable command.
Task 3 Step 5's `FakeBackend` snippet, Task 4 Step 3's threading changes, and
Task 9 Step 3 are described precisely against named interfaces rather than
pasted in full where they are mechanical; each names the exact signature and
behaviour.

**Type consistency:**
- `Turn(role, text)` — Task 1 def, Tasks 1/3/4/5 use.
- `format_context(turns, max_chars=1400) -> str` — Task 1 def, Task 5 use.
- `ConversationStore` method set identical across Tasks 1, 5, 6, 9 test wiring.
- `Backend.route/plan/phrase(..., *, context=None)` + `acknowledge(facts, *,
  context=None)` — Task 3 def, Tasks 4/5 use, `FakeBackend` matches.
- `HandleResult(intent, stored, message, pending=None, cards=[], intent_kind,
  shape)` — Task 4 def, Task 5 reads all fields.
- `Card` union (`RecordCard`/`TaskListCard`/`SourcesCard`) + `EntityRef` — Task 2
  def, Task 4 builders, Task 5 `model_dump`.
- `TurnResponse` / `VoiceOut` fields — Task 5 / Task 6 def, tests read them.
- `VoiceModels.transcriber()/speaker()/health()` — Task 6 def, `FakeVoice` in the
  test matches, Task 8 unaffected (client-side).

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between.
   Order is linear 1 → 10; Task 4 depends on 2+3, Task 5 on 1+4, Task 6 on 5,
   Task 9 on 5.
2. **Inline Execution** — `superpowers:executing-plans`, batched with checkpoints.
