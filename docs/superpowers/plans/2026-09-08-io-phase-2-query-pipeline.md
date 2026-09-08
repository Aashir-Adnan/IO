# IO Phase 2 — Query Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Answer a typed question like "Where have I hung out with Nafay in the past week?" or "What work do I have today?" by planning it into structured + semantic sub-queries, retrieving from PostgreSQL, ranking, expanding recurrences, and phrasing a natural-language answer — all wired into the existing `Orchestrator` so `Route → QUERY` produces a real reply.

**Architecture:** A deterministic pipeline mirroring the STORE side. The model is called only twice: `plan` (question → `QueryPlan`) and `phrase` (ranked rows → answer). Everything between — time-window grounding, SQL compilation, entity resolution, pgvector search, ranking, RRULE expansion — is deterministic Python in `io_assistant/query/`. Structured SQL is the authoritative spine; semantic search only adds rows, never removes them.

**Tech Stack:** Python 3.11+, `uv`, SQLAlchemy 2.x, `pgvector`, `python-dateutil` (`rrule`), `pydantic` v2, `pytest`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-07-io-phase-1-design.md` — read §2 (data flow), §5 (query pipeline, the primary reference), §9 (testing), §13 (backend interface). `.claude/knowledge/query-pipeline.md` is the summary.

## Global Constraints

- **Python** ≥ 3.11. Everything runs through `uv` (`uv run pytest`, `uv run alembic`).
- **Local-first:** no outbound network except `localhost` (Postgres, Ollama) and `api.anthropic.com` when `backend.provider` is `"anthropic"`/`"hybrid"`. Embeddings are always local via `Embedder` (Ollama `nomic-embed-text`, dim 768).
- **LLM boundary (hard rule):** the model does `route`/`extract`/`plan`/`phrase` only. It NEVER emits SQL, does date arithmetic, filters, ranks, or decides entity identity. Time windows and the `kind`/`domain` vocabulary in a plan are grounded/clamped by app code, never trusted raw. See `.claude/rules/llm-boundaries.md`.
- **Migrations:** every schema change is an Alembic migration. Plan 2 adds **no** schema — the HNSW + b-tree + trigram indexes from `0001`/`0002` are what keep retrieval sub-linear.
- **TDD:** failing test first, watch it fail, minimal implementation, watch it pass, commit. Never mock the database — tests run against the real PostgreSQL named by `IO_TEST_DATABASE_URL`. Backend calls use `FakeBackend`; the SQL / ranking / resolver layers never are.
- **Package** is `io_assistant`. DB-touching tests are `@requires_db` and skip cleanly when `IO_TEST_DATABASE_URL` is unset.
- Tests need `IO_TEST_DATABASE_URL` exported in the shell (no `.env` autoload). The dev DB is `docker compose` Postgres+pgvector on `:5432`, databases `io` / `io_test`.

---

## File Structure

```
io_assistant/
  query/
    __init__.py
    plan.py         # SubQuery / QueryPlan pydantic models + ground_plan()
    planner.py      # Planner: question -> QueryPlan (backend.plan + validate + ground + retry)
    entities.py     # resolve_query_entities(): unresolved names -> {etype: [ids]}
    compile.py      # compile_structured(): SubQuery -> SQLAlchemy Select over the target table
    retrieve.py     # retrieve_subquery(): structured + semantic, union by id with provenance
    rank.py         # rank(): weighted blend -> top-N RankedRow list
    recur.py        # expand_recurrences(): RRULE rows -> concrete instances in the window
    respond.py      # Responder: (question, rows, shape) -> str (backend.phrase)
    pipeline.py     # QueryPipeline.answer(): plan -> compile -> retrieve -> rank -> recur -> respond
  prompts/
    plan.txt        # planner prompt (question + now -> QueryPlan JSON)
    respond.txt     # responder prompt (question + rows JSON + shape -> answer)
  backend/
    local.py            # implement plan() + phrase()
    anthropic_backend.py # implement plan() + phrase()
  resolve/
    resolver.py     # add EntityResolver.lookup() — resolve without create/gate
tests/
  fixtures/
    questions_plan.json     # labelled question -> expected grounded QueryPlan shape
  test_query_plan.py        # ground_plan()
  test_query_planner.py     # Planner with FakeBackend
  test_query_entities.py    # resolve_query_entities()
  test_query_compile.py     # compile_structured() -> rows (seeded DB)
  test_query_retrieve.py    # structured + semantic union
  test_query_rank.py        # ranking blend, top-N
  test_query_recur.py       # RRULE expansion
  test_query_respond.py     # Responder with FakeBackend
  test_query_pipeline.py    # QueryPipeline end-to-end with FakeBackend
  test_orchestrator_query.py # QUERY path through Orchestrator (spec scenarios 2 & 3)
  test_backend_local.py     # add plan()/phrase() cases (fake httpx)
  test_backend_anthropic.py # add plan()/phrase() cases (fake client)
```

---

## Task 1: `QueryPlan` domain models + `ground_plan()`

**Files:**
- Create: `io_assistant/query/__init__.py`, `io_assistant/query/plan.py`
- Test: `tests/test_query_plan.py`, `tests/fixtures/questions_plan.json`

**Interfaces:**
- Consumes: `io_assistant.resolve.dates.ground`, `io_assistant.models_domain`
  (`normalize_kind`, `normalize_domain`, `AnswerShape`).
- Produces:
  - `TimeWindow` (pydantic): `start: datetime | None`, `end: datetime | None`.
  - `TargetType` = `Literal["record", "person", "place", "occasion"]`.
  - `Aggregation` = `Literal["list", "count", "latest"]`.
  - `SubQuery` (pydantic): `target_type: TargetType = "record"`,
    `kind_filter: list[str] | None = None`, `domain_filter: list[str] | None = None`,
    `entities: list[str] = []`, `time_window: TimeWindow | None = None`,
    `status_filter: list[str] | None = None`, `semantic_hint: str | None = None`,
    `aggregation: Aggregation = "list"`.
  - `QueryPlan` (pydantic): `subqueries: list[SubQuery]`,
    `answer_shape: AnswerShape = "text"`.
  - `ground_plan(raw: dict, now: datetime) -> QueryPlan` — validates `raw`
    (a parsed-JSON dict from the model) into a `QueryPlan`, then **grounds and
    clamps**:
    - each `time_window`: `start`/`end` may arrive as ISO strings or relative
      phrases (`"last week"`, `"today"`); run each through `ground()`. An
      ungroundable bound becomes `None`. If both are `None` and the phrase was
      relative-past (`"past week"`, `"last N days"`), default `end = now`.
    - `kind_filter`: each entry through `normalize_kind`; drop duplicates; `[]`→`None`.
    - `domain_filter`: each entry through `normalize_domain`; drop `None`s and
      duplicates; `[]`→`None`.
    - `status_filter`: keep only `{"open","done","dropped"}`; `[]`→`None`.
    - `target_type` / `aggregation` / `answer_shape`: coerce an unrecognized
      value to the default (`"record"` / `"list"` / `"text"`).
    - If `subqueries` is empty, synthesize one `SubQuery()` (a bare
      `target_type="record"`, `aggregation="list"` — "everything recent").
  - `PlanError(Exception)` — raised by `ground_plan` only when `raw` is not a
    dict at all.

- [ ] **Step 1: Write the fixture** — `tests/fixtures/questions_plan.json`

```json
[
  {
    "question": "Where have I hung out with Nafay in the past week?",
    "raw": {
      "subqueries": [
        {"target_type": "record", "kind_filter": ["event"],
         "entities": ["Nafay"], "time_window": {"start": "last week", "end": "today"},
         "semantic_hint": "hang out socialise"}
      ],
      "answer_shape": "text"
    },
    "expect": {
      "n_subqueries": 1,
      "kind_filter": ["event"],
      "entities": ["Nafay"],
      "window_start_date": "2026-09-01",
      "window_end_date": "2026-09-08"
    }
  },
  {
    "question": "What work do I have today?",
    "raw": {
      "subqueries": [
        {"target_type": "record", "domain_filter": ["Job"],
         "status_filter": ["open"], "time_window": {"start": null, "end": "today"}},
        {"target_type": "record", "kind_filter": ["Chore"], "status_filter": ["open"]}
      ],
      "answer_shape": "markdown"
    },
    "expect": {
      "n_subqueries": 2,
      "domain_filter_0": ["job"],
      "kind_filter_1": ["chore"],
      "answer_shape": "markdown"
    }
  },
  {
    "question": "hi",
    "raw": {"subqueries": [], "answer_shape": "banana"},
    "expect": {"n_subqueries": 1, "answer_shape": "text"}
  }
]
```

- [ ] **Step 2: Write the failing test** — `tests/test_query_plan.py`

```python
import datetime as dt
import json
from pathlib import Path

import pytest

from io_assistant.query.plan import ground_plan, QueryPlan, PlanError

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)  # a Tuesday
FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "questions_plan.json").read_text()
)


@pytest.mark.parametrize("case", FIXTURES, ids=lambda c: c["question"][:30])
def test_ground_plan_fixtures(case):
    plan = ground_plan(case["raw"], NOW)
    assert isinstance(plan, QueryPlan)
    exp = case["expect"]
    assert len(plan.subqueries) == exp["n_subqueries"]
    if "kind_filter" in exp:
        assert plan.subqueries[0].kind_filter == exp["kind_filter"]
    if "entities" in exp:
        assert plan.subqueries[0].entities == exp["entities"]
    if "window_start_date" in exp:
        assert plan.subqueries[0].time_window.start.date().isoformat() == exp["window_start_date"]
        assert plan.subqueries[0].time_window.end.date().isoformat() == exp["window_end_date"]
    if "domain_filter_0" in exp:
        assert plan.subqueries[0].domain_filter == exp["domain_filter_0"]
    if "kind_filter_1" in exp:
        assert plan.subqueries[1].kind_filter == exp["kind_filter_1"]
    if "answer_shape" in exp:
        assert plan.answer_shape == exp["answer_shape"]


def test_ground_plan_rejects_non_dict():
    with pytest.raises(PlanError):
        ground_plan("not a dict", NOW)


def test_ground_plan_drops_unknown_domain():
    plan = ground_plan(
        {"subqueries": [{"target_type": "record", "domain_filter": ["astrology", "job"]}]},
        NOW,
    )
    assert plan.subqueries[0].domain_filter == ["job"]
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_query_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: io_assistant.query.plan`.

- [ ] **Step 4: Implement `io_assistant/query/__init__.py`** (empty) and
  `io_assistant/query/plan.py`

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from io_assistant.models_domain import (
    AnswerShape,
    normalize_domain,
    normalize_kind,
)
from io_assistant.resolve.dates import ground

TargetType = Literal["record", "person", "place", "occasion"]
Aggregation = Literal["list", "count", "latest"]
_STATUSES = {"open", "done", "dropped"}
_TARGETS = {"record", "person", "place", "occasion"}
_AGGS = {"list", "count", "latest"}
_SHAPES = {"text", "markdown", "diagram"}


class PlanError(Exception):
    pass


class TimeWindow(BaseModel):
    start: datetime | None = None
    end: datetime | None = None


class SubQuery(BaseModel):
    target_type: TargetType = "record"
    kind_filter: list[str] | None = None
    domain_filter: list[str] | None = None
    entities: list[str] = Field(default_factory=list)
    time_window: TimeWindow | None = None
    status_filter: list[str] | None = None
    semantic_hint: str | None = None
    aggregation: Aggregation = "list"


class QueryPlan(BaseModel):
    subqueries: list[SubQuery] = Field(default_factory=list)
    answer_shape: AnswerShape = "text"


def _dedupe(xs: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for x in xs:
        seen.setdefault(x, None)
    return list(seen)


def _ground_bound(value, now: datetime) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    res = ground(str(value), now)
    return res.value if res.ok else None


def _ground_window(raw: dict | None, now: datetime) -> TimeWindow | None:
    if not raw:
        return None
    start = _ground_bound(raw.get("start"), now)
    end = _ground_bound(raw.get("end"), now)
    if start is None and end is None:
        text = " ".join(str(raw.get(k) or "") for k in ("start", "end")).lower()
        if "past" in text or "last" in text or "ago" in text:
            end = now
        else:
            return None
    return TimeWindow(start=start, end=end)


def _clean_subquery(raw: dict, now: datetime) -> SubQuery:
    tt = raw.get("target_type")
    kinds = [normalize_kind(k) for k in (raw.get("kind_filter") or [])]
    domains = [d for d in (normalize_domain(x) for x in (raw.get("domain_filter") or [])) if d]
    statuses = [s for s in (raw.get("status_filter") or []) if s in _STATUSES]
    agg = raw.get("aggregation")
    return SubQuery(
        target_type=tt if tt in _TARGETS else "record",
        kind_filter=_dedupe(kinds) or None,
        domain_filter=_dedupe(domains) or None,
        entities=[str(e) for e in (raw.get("entities") or []) if str(e).strip()],
        time_window=_ground_window(raw.get("time_window"), now),
        status_filter=_dedupe(statuses) or None,
        semantic_hint=(raw.get("semantic_hint") or None),
        aggregation=agg if agg in _AGGS else "list",
    )


def ground_plan(raw: object, now: datetime) -> QueryPlan:
    if not isinstance(raw, dict):
        raise PlanError(f"plan must be a JSON object, got {type(raw).__name__}")
    subs_raw = raw.get("subqueries") or []
    subs = [_clean_subquery(s, now) for s in subs_raw if isinstance(s, dict)]
    if not subs:
        subs = [SubQuery()]
    shape = raw.get("answer_shape")
    return QueryPlan(
        subqueries=subs,
        answer_shape=shape if shape in _SHAPES else "text",
    )
```

- [ ] **Step 5: Run to verify it passes**

Run: `uv run pytest tests/test_query_plan.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/query/ tests/test_query_plan.py tests/fixtures/questions_plan.json
git commit -m "feat: QueryPlan domain models and ground_plan() grounding/clamping"
```

---

## Task 2: `Planner` + `Backend.plan` real implementations

**Files:**
- Create: `io_assistant/query/planner.py`, `io_assistant/prompts/plan.txt`
- Modify: `io_assistant/backend/interface.py`, `io_assistant/backend/local.py`,
  `io_assistant/backend/anthropic_backend.py`, `tests/conftest.py` (FakeBackend)
- Test: `tests/test_query_planner.py`, `tests/test_backend_local.py`,
  `tests/test_backend_anthropic.py`

**Interfaces:**
- Consumes: `Backend.plan`, `ground_plan` (Task 1), `BackendParseError`.
- Produces:
  - `Backend.plan(self, question: str, now: datetime) -> dict` — the protocol
    signature is unchanged (still `-> dict`); it now returns the **parsed JSON
    object** the model produced (not grounded). Raises `BackendParseError` if
    the body will not parse as a JSON object.
  - `LocalBackend.plan` / `AnthropicBackend.plan` — real: render `plan.txt`,
    call the model in JSON mode, `json.loads`, return the dict. On parse
    failure raise `BackendParseError`. Same shape as their `extract`.
    `HybridBackend.plan` already delegates to the cloud backend — no change.
  - `FakeBackend.set_plan(d: dict)` + `plan()` returns it (conftest).
  - `Planner(backend)` with `run(self, question: str, now: datetime) -> QueryPlan`
    — calls `backend.plan`, grounds via `ground_plan`; on `BackendParseError`
    or `PlanError` retries once, then falls back to
    `QueryPlan(subqueries=[SubQuery(semantic_hint=question)])` so a question
    always produces *some* retrieval.

- [ ] **Step 1: Write `io_assistant/prompts/plan.txt`**

```
You convert ONE user question into a retrieval plan as a single JSON object.

Shape:
{
  "subqueries": [
    {
      "target_type": "record" | "person" | "place" | "occasion",
      "kind_filter": ["event" | "task" | "chore" | "<slug>", ...] | null,
      "domain_filter": ["social"|"job"|"home"|"health"|"finance"|"learning"|"errand"|"other", ...] | null,
      "entities": ["<name as written>", ...],
      "time_window": {"start": "<phrase or ISO or null>", "end": "<phrase or ISO or null>"} | null,
      "status_filter": ["open"|"done"|"dropped", ...] | null,
      "semantic_hint": "<short phrase to embed>" | null,
      "aggregation": "list" | "count" | "latest" | null
    }
  ],
  "answer_shape": "text" | "markdown" | "diagram"
}

Rules:
- Copy time expressions as raw phrases ("last week", "yesterday", "past month").
  Never compute a date.
- A simple question is ONE subquery. Use two only when the question genuinely
  asks for two different sets (e.g. "work" = job records + chores).
- entities: names exactly as the user wrote them, unresolved.
- semantic_hint: only when wording matters beyond the filters; else null.
- answer_shape: "markdown" for lists/tables, "diagram" only if a chart/timeline
  is asked for, else "text".

Question (assume "now" is {now}):
{question}

Output the JSON object only:
```

- [ ] **Step 2: Write the failing test** — `tests/test_query_planner.py`

```python
import datetime as dt

import pytest

from io_assistant.query.planner import Planner
from io_assistant.query.plan import QueryPlan

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)


def test_planner_grounds_backend_output(fake_backend):
    fake_backend.set_plan({
        "subqueries": [{"target_type": "record", "kind_filter": ["event"],
                        "entities": ["Nafay"],
                        "time_window": {"start": "last week", "end": "today"}}],
        "answer_shape": "text",
    })
    plan = Planner(fake_backend).run("where did I see Nafay", NOW)
    assert isinstance(plan, QueryPlan)
    sq = plan.subqueries[0]
    assert sq.kind_filter == ["event"] and sq.entities == ["Nafay"]
    assert sq.time_window.start.date().isoformat() == "2026-09-01"


def test_planner_falls_back_on_unparseable(fake_backend, monkeypatch):
    from io_assistant.backend.interface import BackendParseError

    def boom(*a, **k):
        raise BackendParseError("no json")

    fake_backend.plan = boom
    plan = Planner(fake_backend).run("something vague", NOW)
    assert len(plan.subqueries) == 1
    assert plan.subqueries[0].semantic_hint == "something vague"
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_query_planner.py -v`
Expected: FAIL — no `Planner`, no `fake_backend.set_plan`.

- [ ] **Step 4: Update the `Backend` protocol** — `io_assistant/backend/interface.py`

Change the `plan` docstring/signature note (keep `-> dict`):
```python
    def plan(self, question: str, now: datetime) -> dict:
        """Return the model's retrieval plan as a parsed JSON object (dict).
        Grounding/clamping happens in io_assistant.query.plan.ground_plan.
        Raise BackendParseError if the output is not a JSON object."""
        ...
```

- [ ] **Step 5: Add `set_plan` / `plan` to `FakeBackend`** — `tests/conftest.py`

```python
    def set_plan(self, d: dict):
        self._plan = d
```
and in `__init__` add `self._plan: dict = {}`, and change `plan`:
```python
    def plan(self, question: str, now: datetime) -> dict:
        self.calls.append("plan")
        return self._plan
```

- [ ] **Step 6: Implement `Planner`** — `io_assistant/query/planner.py`

```python
from __future__ import annotations

from datetime import datetime

from io_assistant.backend.interface import Backend, BackendParseError
from io_assistant.query.plan import QueryPlan, SubQuery, ground_plan, PlanError


class Planner:
    def __init__(self, backend: Backend):
        self._backend = backend

    def run(self, question: str, now: datetime) -> QueryPlan:
        for attempt in (1, 2):
            try:
                raw = self._backend.plan(question, now)
                return ground_plan(raw, now)
            except (BackendParseError, PlanError):
                if attempt == 2:
                    break
        return QueryPlan(subqueries=[SubQuery(semantic_hint=question)])
```

- [ ] **Step 7: Implement `LocalBackend.plan`** — `io_assistant/backend/local.py`

```python
    def plan(self, question: str, now: datetime) -> dict:
        out = self._chat(
            "You convert a question into a retrieval plan. Output one JSON "
            "object and nothing else.",
            _load_prompt("plan.txt").format(now=now.isoformat(), question=question),
            json_mode=True,
        )
        try:
            data = json.loads(out)
        except (json.JSONDecodeError, TypeError) as e:
            raise BackendParseError(str(e)) from e
        if not isinstance(data, dict):
            raise BackendParseError(f"plan is not an object: {out!r}")
        return data
```
Add `import json` at the top of `local.py` if not present.

- [ ] **Step 8: Implement `AnthropicBackend.plan`** — `io_assistant/backend/anthropic_backend.py`

```python
    def plan(self, question: str, now: datetime) -> dict:
        out = self._complete(
            "You convert a question into a retrieval plan. Output one JSON "
            "object and nothing else.",
            _prompt("plan.txt").format(now=now.isoformat(), question=question),
            max_tokens=512,
        )
        out = out.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            data = json.loads(out)
        except (json.JSONDecodeError, TypeError) as e:
            raise BackendParseError(str(e)) from e
        if not isinstance(data, dict):
            raise BackendParseError(f"plan is not an object: {out!r}")
        return data
```
Add `import json` at the top of `anthropic_backend.py`.

- [ ] **Step 9: Add backend unit tests**

`tests/test_backend_local.py`:
```python
def test_local_plan_parses_json(config, monkeypatch):
    _patch_chat(monkeypatch, '{"subqueries": [], "answer_shape": "text"}')
    out = LocalBackend(config).plan("what did I do", dt.datetime.now(dt.timezone.utc))
    assert out == {"subqueries": [], "answer_shape": "text"}


def test_local_plan_bad_json_raises(config, monkeypatch):
    _patch_chat(monkeypatch, "not json")
    with pytest.raises(BackendParseError):
        LocalBackend(config).plan("x", dt.datetime.now(dt.timezone.utc))
```
(`_patch_chat` is the existing helper in that file.)

`tests/test_backend_anthropic.py`:
```python
def test_anthropic_plan_parses(config):
    c = FakeClient('{"subqueries":[{"target_type":"record"}],"answer_shape":"text"}')
    out = AnthropicBackend(config, client=c).plan("q", dt.datetime.now(dt.timezone.utc))
    assert out["subqueries"][0]["target_type"] == "record"
```

- [ ] **Step 10: Run all touched tests**

Run: `uv run pytest tests/test_query_planner.py tests/test_backend_local.py tests/test_backend_anthropic.py tests/test_backend_interface.py -v`
Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add io_assistant/query/planner.py io_assistant/prompts/plan.txt io_assistant/backend/ tests/
git commit -m "feat: Planner + LocalBackend/AnthropicBackend plan() implementations"
```

---

## Task 3: `EntityResolver.lookup()` + `resolve_query_entities()`

**Files:**
- Modify: `io_assistant/resolve/resolver.py`
- Create: `io_assistant/query/entities.py`
- Test: `tests/test_resolve.py`, `tests/test_query_entities.py`

**Interfaces:**
- Consumes: `EntityResolver` (its `_candidate_rows` + fuzzy logic).
- Produces:
  - `EntityResolver.lookup(self, entity_type, name) -> int | None` — exact →
    fuzzy → vector, returning the matched id or `None`. **No create, no gate,
    no ambiguity** — a vector-only near-match counts as a hit here (queries are
    read-only; a wrong link just widens recall slightly). Reuses
    `_candidate_rows`.
  - `resolve_query_entities(resolver, names: list[str]) -> dict[str, list[int]]`
    in `query/entities.py` — maps each raw name to matched ids across all three
    entity types (`person`/`place`/`item`), keyed by `"person"`/`"place"`/
    `"item"`/`"occasion"`. Occasions are matched by case-insensitive name via a
    direct query (they are not `EntityResolver` types). Returns
    `{"person": [...], "place": [...], "item": [...], "occasion": [...]}` —
    ids only, deduped, order-preserving. Unmatched names contribute nothing.

- [ ] **Step 1: Write the failing tests** — `tests/test_resolve.py` (append)

```python
@requires_db
def test_lookup_returns_id_or_none(db, config):
    db.add(m.Person(canonical_name="Nafay", aliases=[]))
    db.flush()
    r = EntityResolver(db, StubEmbedder(), config.resolver)
    assert isinstance(r.lookup("person", "nafay"), int)
    assert r.lookup("person", "Absolutely Nobody") is None
```

`tests/test_query_entities.py`:
```python
import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.resolve.resolver import EntityResolver
from io_assistant.query.entities import resolve_query_entities


class _Emb:
    def embed_one(self, t): return [0.0] * 768
    def embed(self, ts): return [[0.0] * 768 for _ in ts]


@requires_db
def test_resolve_query_entities(db, config):
    db.add_all([
        m.Person(canonical_name="Nafay", aliases=[]),
        m.Place(name="Arcadian", type=None, aliases=[]),
        m.Occasion(name="Nafay's birthday", date=None),
    ])
    db.flush()
    r = EntityResolver(db, _Emb(), config.resolver)
    out = resolve_query_entities(r, db, ["Nafay", "Arcadian", "Nafay's birthday", "Ghost"])
    assert len(out["person"]) == 1
    assert len(out["place"]) == 1
    assert len(out["occasion"]) == 1
    assert out["item"] == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_resolve.py::test_lookup_returns_id_or_none tests/test_query_entities.py -v`
Expected: FAIL — no `lookup`, no `query.entities`.

- [ ] **Step 3: Implement `EntityResolver.lookup`** — `io_assistant/resolve/resolver.py`

```python
    def lookup(self, entity_type: EntityType, name: str) -> int | None:
        """Read-only resolve for queries: exact -> fuzzy -> vector, best id or
        None. No create, no gate — a near vector match still counts."""
        rows = self._candidate_rows(entity_type, name, [])
        lowered = name.lower()
        for cid, cname, caliases in rows:
            stored = {cname.lower(), *[a.lower() for a in (caliases or [])]}
            if lowered in stored:
                return cid
        best_id, best_score = None, -1.0
        for cid, cname, caliases in rows:
            score = max(
                fuzz.token_set_ratio(name, c) for c in (cname, *(caliases or []))
            )
            if score > best_score:
                best_score, best_id = score, cid
        if best_id is not None and best_score >= self.cfg.fuzzy_threshold:
            return best_id

        model, name_col = self._model_col(entity_type)
        vec = self.embedder.embed_one(name)
        dist = model.embedding.cosine_distance(vec).label("dist")
        row = self.session.execute(
            select(model.id, dist).where(model.embedding.isnot(None))
            .order_by(dist.asc()).limit(1)
        ).first()
        if row is not None and (1.0 - float(row[1])) >= self.cfg.vector_similarity_threshold:
            return row[0]
        return None
```

- [ ] **Step 4: Implement `io_assistant/query/entities.py`**

```python
from __future__ import annotations

from sqlalchemy import func, select

from io_assistant.db import models as m
from io_assistant.resolve.resolver import EntityResolver

_TYPES = ("person", "place", "item")


def resolve_query_entities(
    resolver: EntityResolver, session, names: list[str]
) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {"person": [], "place": [], "item": [], "occasion": []}
    for name in names:
        for etype in _TYPES:
            eid = resolver.lookup(etype, name)
            if eid is not None and eid not in out[etype]:
                out[etype].append(eid)
        occ = session.execute(
            select(m.Occasion.id).where(func.lower(m.Occasion.name) == name.lower())
        ).scalars().first()
        if occ is not None and occ not in out["occasion"]:
            out["occasion"].append(occ)
    return out
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/test_resolve.py tests/test_query_entities.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/resolve/resolver.py io_assistant/query/entities.py tests/
git commit -m "feat: EntityResolver.lookup() and resolve_query_entities() for queries"
```

---

## Task 4: `compile_structured()` — SubQuery → SQL

**Files:**
- Create: `io_assistant/query/compile.py`
- Test: `tests/test_query_compile.py`

**Interfaces:**
- Consumes: `SubQuery`, `TimeWindow` (Task 1); `resolve_query_entities` output
  shape (Task 3); `io_assistant.db.models`.
- Produces:
  - `compile_structured(sq: SubQuery, entity_ids: dict[str, list[int]], now: datetime) -> Select`
    — a SQLAlchemy `Select` over the table for `sq.target_type`
    (`record`→`Record`, `person`→`Person`, `place`→`Place`, `occasion`→`Occasion`),
    applying:
    - **target `record`:** `kind IN kind_filter`, `domain IN domain_filter`,
      `status IN status_filter`; time window on
      `coalesce(occurred_at, due_at, created_at)` between `start` and `end`
      (open-ended if a bound is `None`); entity links — for each non-empty list
      in `entity_ids`, an `EXISTS` against the matching link table
      (`record_people`/`record_places`/`record_items`/`record_occasions`) with
      `*_id IN (...)`. Multiple entity types are AND-ed (a record about Nafay
      *and* Arcadian).
    - **target `person`/`place`/`occasion`:** filter by `id IN` the matching
      `entity_ids` list when present; time window on `created_at` (and
      `occasions.date` when `target_type == "occasion"`).
    - always `ORDER BY <recency col> DESC`, `LIMIT 200` (a hard cap before
      ranking; ranking then trims to top-N).
  - `recency_column(target_type)` helper returning the SQLAlchemy column used
    for ordering / recency scoring.

- [ ] **Step 1: Write the failing test** — `tests/test_query_compile.py`

```python
import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.query.plan import SubQuery, TimeWindow
from io_assistant.query.compile import compile_structured

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)


def _utt(db):
    u = m.Utterance(text="seed", source="text", captured_at=NOW)
    db.add(u); db.flush()
    return u.id


@requires_db
def test_compile_filters_kind_and_window(db):
    uid = _utt(db)
    db.add_all([
        m.Record(kind="event", title="dinner", occurred_at=NOW - dt.timedelta(days=2),
                 attributes={}, source_utterance_id=uid),
        m.Record(kind="event", title="old dinner", occurred_at=NOW - dt.timedelta(days=90),
                 attributes={}, source_utterance_id=uid),
        m.Record(kind="task", title="a task", due_at=NOW, attributes={},
                 source_utterance_id=uid),
    ])
    db.flush()
    sq = SubQuery(target_type="record", kind_filter=["event"],
                  time_window=TimeWindow(start=NOW - dt.timedelta(days=7), end=NOW))
    rows = db.execute(compile_structured(sq, {"person": [], "place": [], "item": [], "occasion": []}, NOW)).all()
    titles = {r[0].title for r in rows}
    assert titles == {"dinner"}


@requires_db
def test_compile_entity_link_exists(db):
    uid = _utt(db)
    p = m.Person(canonical_name="Nafay", aliases=[]); db.add(p); db.flush()
    r1 = m.Record(kind="event", title="with nafay", occurred_at=NOW, attributes={},
                  source_utterance_id=uid)
    r2 = m.Record(kind="event", title="alone", occurred_at=NOW, attributes={},
                  source_utterance_id=uid)
    db.add_all([r1, r2]); db.flush()
    db.add(m.RecordPerson(record_id=r1.id, person_id=p.id)); db.flush()
    sq = SubQuery(target_type="record", entities=["Nafay"])
    rows = db.execute(compile_structured(
        sq, {"person": [p.id], "place": [], "item": [], "occasion": []}, NOW)).all()
    assert {r[0].title for r in rows} == {"with nafay"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_query_compile.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `io_assistant/query/compile.py`**

```python
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select

from io_assistant.db import models as m
from io_assistant.query.plan import SubQuery

_TARGET_MODEL = {
    "record": m.Record,
    "person": m.Person,
    "place": m.Place,
    "occasion": m.Occasion,
}
_LINK = {
    "person": (m.RecordPerson, m.RecordPerson.person_id, m.RecordPerson.record_id),
    "place": (m.RecordPlace, m.RecordPlace.place_id, m.RecordPlace.record_id),
    "item": (m.RecordItem, m.RecordItem.item_id, m.RecordItem.record_id),
    "occasion": (m.RecordOccasion, m.RecordOccasion.occasion_id, m.RecordOccasion.record_id),
}
_LIMIT = 200


def recency_column(target_type: str):
    if target_type == "record":
        return func.coalesce(m.Record.occurred_at, m.Record.due_at, m.Record.created_at)
    if target_type == "occasion":
        return func.coalesce(m.Occasion.date, m.Occasion.created_at)
    return _TARGET_MODEL[target_type].created_at


def compile_structured(
    sq: SubQuery, entity_ids: dict[str, list[int]], now: datetime
) -> Select:
    model = _TARGET_MODEL[sq.target_type]
    recency = recency_column(sq.target_type)
    stmt = select(model)
    conds = []

    if sq.target_type == "record":
        if sq.kind_filter:
            conds.append(m.Record.kind.in_(sq.kind_filter))
        if sq.domain_filter:
            conds.append(m.Record.domain.in_(sq.domain_filter))
        if sq.status_filter:
            conds.append(m.Record.status.in_(sq.status_filter))
        for etype, (link, link_eid, link_rid) in _LINK.items():
            ids = entity_ids.get(etype) or []
            if ids:
                conds.append(
                    select(link_rid)
                    .where(and_(link_rid == m.Record.id, link_eid.in_(ids)))
                    .exists()
                )
    else:
        ids = entity_ids.get(sq.target_type) or []
        if ids:
            conds.append(model.id.in_(ids))

    if sq.time_window is not None:
        if sq.time_window.start is not None:
            conds.append(recency >= sq.time_window.start)
        if sq.time_window.end is not None:
            conds.append(recency <= sq.time_window.end)

    if conds:
        stmt = stmt.where(and_(*conds))
    return stmt.order_by(recency.desc()).limit(_LIMIT)
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_query_compile.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/query/compile.py tests/test_query_compile.py
git commit -m "feat: compile_structured() — SubQuery to parameterized SQL"
```

---

## Task 5: `retrieve_subquery()` — structured + semantic union

**Files:**
- Create: `io_assistant/query/retrieve.py`
- Test: `tests/test_query_retrieve.py`

**Interfaces:**
- Consumes: `compile_structured` (Task 4), `recency_column`, `Embedder`,
  `SubQuery`.
- Produces:
  - `Provenance` = `Literal["structured", "semantic", "both"]`.
  - `RetrievedRow` (dataclass): `obj` (the ORM row), `target_type: str`,
    `provenance: Provenance`, `distance: float | None` (cosine distance from the
    semantic hint, `None` when structured-only).
  - `retrieve_subquery(session, embedder, sq, entity_ids, now) -> list[RetrievedRow]`
    — runs `compile_structured` (the authoritative spine). If
    `sq.semantic_hint`, embeds it and runs a pgvector nearest-neighbour search
    on the **same target table**, `WHERE embedding IS NOT NULL`, constrained to
    the **same time window** (reuse `recency_column`), `ORDER BY cosine_distance
    LIMIT 50`. Union by primary-key id; a row in both sets is `"both"` and keeps
    the semantic `distance`.

- [ ] **Step 1: Write the failing test** — `tests/test_query_retrieve.py`

```python
import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.query.plan import SubQuery, TimeWindow
from io_assistant.query.retrieve import retrieve_subquery

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)
EMPTY = {"person": [], "place": [], "item": [], "occasion": []}


class VecEmbedder:
    def __init__(self, vec): self.vec = vec
    def embed_one(self, t): return self.vec
    def embed(self, ts): return [self.vec for _ in ts]


def _uid(db):
    u = m.Utterance(text="s", source="text", captured_at=NOW); db.add(u); db.flush()
    return u.id


@requires_db
def test_retrieve_unions_structured_and_semantic(db):
    uid = _uid(db)
    near = m.Record(kind="note", title="gym leg day", occurred_at=NOW, attributes={},
                    source_utterance_id=uid, embedding=[1.0] + [0.0] * 767)
    far = m.Record(kind="note", title="tax return", occurred_at=NOW, attributes={},
                   source_utterance_id=uid, embedding=[0.0] * 767 + [1.0])
    db.add_all([near, far]); db.flush()
    sq = SubQuery(target_type="record", kind_filter=["note"],
                  semantic_hint="workout", 
                  time_window=TimeWindow(start=NOW - dt.timedelta(days=1), end=NOW))
    rows = retrieve_subquery(db, VecEmbedder([1.0] + [0.0] * 767), sq, EMPTY, NOW)
    by_title = {r.obj.title: r for r in rows}
    assert by_title["gym leg day"].provenance == "both"
    assert by_title["tax return"].provenance == "structured"
    assert by_title["gym leg day"].distance is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_query_retrieve.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `io_assistant/query/retrieve.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import select

from io_assistant.query.compile import compile_structured, recency_column, _TARGET_MODEL
from io_assistant.query.plan import SubQuery

Provenance = Literal["structured", "semantic", "both"]
_SEMANTIC_LIMIT = 50


@dataclass
class RetrievedRow:
    obj: object
    target_type: str
    provenance: Provenance
    distance: float | None


def retrieve_subquery(
    session, embedder, sq: SubQuery, entity_ids: dict[str, list[int]], now: datetime
) -> list[RetrievedRow]:
    model = _TARGET_MODEL[sq.target_type]
    structured = session.execute(
        compile_structured(sq, entity_ids, now)
    ).scalars().all()
    rows: dict[int, RetrievedRow] = {
        obj.id: RetrievedRow(obj, sq.target_type, "structured", None)
        for obj in structured
    }

    if sq.semantic_hint:
        vec = embedder.embed_one(sq.semantic_hint)
        dist = model.embedding.cosine_distance(vec).label("dist")
        stmt = select(model, dist).where(model.embedding.isnot(None))
        if sq.time_window is not None:
            recency = recency_column(sq.target_type)
            if sq.time_window.start is not None:
                stmt = stmt.where(recency >= sq.time_window.start)
            if sq.time_window.end is not None:
                stmt = stmt.where(recency <= sq.time_window.end)
        stmt = stmt.order_by(dist.asc()).limit(_SEMANTIC_LIMIT)
        for obj, d in session.execute(stmt).all():
            d = float(d)
            if obj.id in rows:
                rows[obj.id].provenance = "both"
                rows[obj.id].distance = d
            else:
                rows[obj.id] = RetrievedRow(obj, sq.target_type, "semantic", d)

    return list(rows.values())
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_query_retrieve.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/query/retrieve.py tests/test_query_retrieve.py
git commit -m "feat: retrieve_subquery() — structured spine + bounded semantic union"
```

---

## Task 6: `rank()` — merge & rank across subqueries

**Files:**
- Create: `io_assistant/query/rank.py`
- Test: `tests/test_query_rank.py`

**Interfaces:**
- Consumes: `RetrievedRow` (Task 5).
- Produces:
  - `RankedRow` (dataclass): `obj`, `target_type: str`, `provenance: str`,
    `score: float`, `components: dict[str, float]` (for debugging/tests).
  - `rank(groups: list[list[RetrievedRow]], now: datetime, *, top_n: int = 20) -> list[RankedRow]`
    — flatten all subquery result lists, dedupe by `(target_type, id)` keeping
    the strongest provenance (`both` > structured/semantic) and smallest
    distance, then score each row as a weighted blend, normalised to `[0, 1]`:
    - `recency`: `exp(-age_days / 30)` where `age_days` is from `now` to the
      row's recency column value (0 when null).
    - `similarity`: `1 - distance` (0 when `distance` is `None`).
    - `structured_relevance`: `1.0` if the row came from the structured spine
      (`provenance != "semantic"`), else `0.4`.
    - `provenance_bonus`: `0.15` when `provenance == "both"`, else `0`.
    - `score = 0.30*recency + 0.30*similarity + 0.30*structured_relevance + provenance_bonus`
    Sort by `score` desc, stable; return the first `top_n`.

- [ ] **Step 1: Write the failing test** — `tests/test_query_rank.py`

```python
import datetime as dt
import types

from io_assistant.query.retrieve import RetrievedRow
from io_assistant.query.rank import rank

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)


def _row(rid, title, days_ago, created=None):
    return types.SimpleNamespace(
        id=rid, title=title,
        occurred_at=NOW - dt.timedelta(days=days_ago), due_at=None,
        created_at=created or (NOW - dt.timedelta(days=days_ago)),
    )


def test_both_provenance_and_recency_win():
    recent_both = RetrievedRow(_row(1, "recent+both", 1), "record", "both", 0.1)
    old_structured = RetrievedRow(_row(2, "old", 200), "record", "structured", None)
    semantic_only = RetrievedRow(_row(3, "sem", 2), "record", "semantic", 0.2)
    out = rank([[recent_both, old_structured], [semantic_only]], NOW, top_n=3)
    assert [r.obj.id for r in out][0] == 1
    assert len(out) == 3


def test_dedupe_keeps_both():
    a = RetrievedRow(_row(9, "x", 1), "record", "structured", None)
    b = RetrievedRow(_row(9, "x", 1), "record", "semantic", 0.05)
    out = rank([[a], [b]], NOW)
    assert len(out) == 1 and out[0].provenance == "both"


def test_top_n_caps():
    rows = [RetrievedRow(_row(i, str(i), i), "record", "structured", None) for i in range(50)]
    assert len(rank([rows], NOW, top_n=20)) == 20
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_query_rank.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `io_assistant/query/rank.py`**

```python
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from io_assistant.query.retrieve import RetrievedRow

_STRONGER = {"structured": 1, "semantic": 1, "both": 2}


@dataclass
class RankedRow:
    obj: object
    target_type: str
    provenance: str
    score: float
    components: dict[str, float] = field(default_factory=dict)


def _recency_value(obj):
    for attr in ("occurred_at", "due_at", "date", "created_at"):
        v = getattr(obj, attr, None)
        if v is not None:
            return v
    return None


def _merge(groups: list[list[RetrievedRow]]) -> list[RetrievedRow]:
    best: dict[tuple[str, int], RetrievedRow] = {}
    for group in groups:
        for r in group:
            key = (r.target_type, r.obj.id)
            cur = best.get(key)
            if cur is None:
                best[key] = RetrievedRow(r.obj, r.target_type, r.provenance, r.distance)
                continue
            if r.provenance != cur.provenance and {r.provenance, cur.provenance} <= {"structured", "semantic"}:
                cur.provenance = "both"
            elif _STRONGER[r.provenance] > _STRONGER[cur.provenance]:
                cur.provenance = r.provenance
            if r.distance is not None and (cur.distance is None or r.distance < cur.distance):
                cur.distance = r.distance
    return list(best.values())


def rank(
    groups: list[list[RetrievedRow]], now: datetime, *, top_n: int = 20
) -> list[RankedRow]:
    out: list[RankedRow] = []
    for r in _merge(groups):
        rv = _recency_value(r.obj)
        if rv is not None:
            age_days = max(0.0, (now - _as_dt(rv, now)).total_seconds() / 86400.0)
        else:
            age_days = 365.0
        recency = math.exp(-age_days / 30.0)
        similarity = (1.0 - r.distance) if r.distance is not None else 0.0
        structured_rel = 1.0 if r.provenance != "semantic" else 0.4
        prov_bonus = 0.15 if r.provenance == "both" else 0.0
        score = 0.30 * recency + 0.30 * similarity + 0.30 * structured_rel + prov_bonus
        out.append(RankedRow(
            r.obj, r.target_type, r.provenance, score,
            {"recency": recency, "similarity": similarity,
             "structured": structured_rel, "provenance": prov_bonus},
        ))
    out.sort(key=lambda x: x.score, reverse=True)
    return out[:top_n]


def _as_dt(v, now: datetime):
    import datetime as _dt
    if isinstance(v, _dt.datetime):
        return v if v.tzinfo else v.replace(tzinfo=now.tzinfo)
    if isinstance(v, _dt.date):
        return _dt.datetime(v.year, v.month, v.day, tzinfo=now.tzinfo)
    return now
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_query_rank.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/query/rank.py tests/test_query_rank.py
git commit -m "feat: rank() — weighted merge/rank with top-N cap"
```

---

## Task 7: `expand_recurrences()` — RRULE → concrete instances

**Files:**
- Create: `io_assistant/query/recur.py`
- Test: `tests/test_query_recur.py`

**Interfaces:**
- Consumes: `RankedRow` (Task 6); `dateutil.rrule`.
- Produces:
  - `RecurrenceInstance` (dataclass): `obj`, `target_type: str`, `score: float`,
    `occurs_at: datetime` — one per concrete firing.
  - `expand_recurrences(rows: list[RankedRow], window_start: datetime | None, window_end: datetime | None, *, now: datetime) -> list[RankedRow | RecurrenceInstance]`
    — for each row whose `obj` has a non-empty `recurrence_rule` (records and
    occasions), parse it with
    `dateutil.rrule.rrulestr("RRULE:" + rule, dtstart=<anchor>)` and yield a
    `RecurrenceInstance` for each firing within
    `[window_start or now-30d, window_end or now+30d]` (cap 50 instances per
    row). The row's own `score` is copied onto each instance. Non-recurring
    rows pass through unchanged. Rows with an unparseable rule pass through
    unchanged (log-free — the store-side gate already caught unreadable ones).
  - `anchor_for(obj)` helper: `occurred_at` or `due_at` or `date` or
    `created_at`, as a timezone-aware `datetime`.

- [ ] **Step 1: Write the failing test** — `tests/test_query_recur.py`

```python
import datetime as dt
import types

from io_assistant.query.rank import RankedRow
from io_assistant.query.recur import expand_recurrences, RecurrenceInstance

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)  # Tuesday


def _rr(rule, anchor_days_ago=7):
    obj = types.SimpleNamespace(
        id=1, title="trash", recurrence_rule=rule,
        occurred_at=None, due_at=None, date=None,
        created_at=NOW - dt.timedelta(days=anchor_days_ago),
    )
    return RankedRow(obj, "record", "structured", 0.5)


def test_weekly_rule_expands_within_window():
    out = expand_recurrences([_rr("FREQ=WEEKLY;BYDAY=MO")],
                             NOW - dt.timedelta(days=21), NOW, now=NOW)
    insts = [x for x in out if isinstance(x, RecurrenceInstance)]
    assert len(insts) == 3
    assert all(i.occurs_at.weekday() == 0 for i in insts)


def test_non_recurring_passes_through():
    plain = RankedRow(types.SimpleNamespace(id=2, recurrence_rule=None), "record", "both", 0.9)
    out = expand_recurrences([plain], None, None, now=NOW)
    assert out == [plain]


def test_unparseable_rule_passes_through():
    bad = _rr("FREQ=NONSENSE")
    out = expand_recurrences([bad], NOW - dt.timedelta(days=7), NOW, now=NOW)
    assert out == [bad]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_query_recur.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement `io_assistant/query/recur.py`**

```python
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from datetime import datetime, timedelta

from dateutil.rrule import rrulestr

from io_assistant.query.rank import RankedRow

_MAX_INSTANCES = 50


@dataclass
class RecurrenceInstance:
    obj: object
    target_type: str
    score: float
    occurs_at: datetime


def anchor_for(obj, now: datetime) -> datetime:
    for attr in ("occurred_at", "due_at", "date", "created_at"):
        v = getattr(obj, attr, None)
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=now.tzinfo)
        if isinstance(v, _dt.date):
            return datetime(v.year, v.month, v.day, tzinfo=now.tzinfo)
    return now


def expand_recurrences(
    rows: list[RankedRow],
    window_start: datetime | None,
    window_end: datetime | None,
    *,
    now: datetime,
) -> list:
    lo = window_start or (now - timedelta(days=30))
    hi = window_end or (now + timedelta(days=30))
    out: list = []
    for row in rows:
        rule = getattr(row.obj, "recurrence_rule", None)
        if not rule:
            out.append(row)
            continue
        try:
            rs = rrulestr("RRULE:" + rule, dtstart=anchor_for(row.obj, now))
            fires = list(rs.between(lo, hi, inc=True))[:_MAX_INSTANCES]
        except (ValueError, TypeError):
            out.append(row)
            continue
        if not fires:
            out.append(row)
            continue
        for when in fires:
            out.append(RecurrenceInstance(row.obj, row.target_type, row.score, when))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_query_recur.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/query/recur.py tests/test_query_recur.py
git commit -m "feat: expand_recurrences() — RRULE firings within the query window"
```

---

## Task 8: `Responder` + `Backend.phrase` implementations

**Files:**
- Create: `io_assistant/query/respond.py`, `io_assistant/prompts/respond.txt`
- Modify: `io_assistant/backend/local.py`, `io_assistant/backend/anthropic_backend.py`
- Test: `tests/test_query_respond.py`, `tests/test_backend_local.py`,
  `tests/test_backend_anthropic.py`

**Interfaces:**
- Consumes: `Backend.phrase`, `RankedRow` / `RecurrenceInstance`.
- Produces:
  - `LocalBackend.phrase` / `AnthropicBackend.phrase` — real: render
    `respond.txt` with the question, a JSON array of row dicts, and the shape;
    return the model's text. Not JSON mode. `HybridBackend.phrase` already
    delegates to cloud.
  - `rows_to_json(rows: list) -> list[dict]` in `respond.py` — projects each
    `RankedRow`/`RecurrenceInstance` to a compact dict: `type`, `title`,
    `kind`/`domain`/`status` (records), `when` (ISO of the recency value or the
    recurrence instance), `name`/`date` (person/place/occasion). No embeddings,
    no ids beyond what's useful.
  - `Responder(backend)` with
    `run(self, question: str, rows: list, shape: str) -> str` — if `rows` is
    empty, returns a deterministic `"I don't have anything on that yet."`
    without calling the model (spec §5.5 "state explicitly when nothing
    matched" — cheaper and reliable). Otherwise calls
    `backend.phrase(question, rows_to_json(rows), shape)`.

- [ ] **Step 1: Write `io_assistant/prompts/respond.txt`**

```
Answer the user's question using ONLY the rows provided. Do not invent facts,
dates, names, or numbers that are not in the rows. If the rows do not answer
the question, say so plainly.

Shape:
- "text": one or two plain sentences.
- "markdown": short markdown, a bullet list or small table when there are
  several rows.
- "diagram": a single fenced ```mermaid block and nothing else.

Question:
{question}

Rows (JSON):
{rows}

Answer ({shape}):
```

- [ ] **Step 2: Write the failing test** — `tests/test_query_respond.py`

```python
import types

from io_assistant.query.respond import Responder, rows_to_json
from io_assistant.query.rank import RankedRow


def test_empty_rows_short_circuits(fake_backend):
    out = Responder(fake_backend).run("what did I do?", [], "text")
    assert "anything" in out.lower()
    assert "phrase" not in fake_backend.calls


def test_calls_backend_with_projected_rows(fake_backend):
    fake_backend.set_answer("You had dinner with Nafay.")
    row = RankedRow(
        types.SimpleNamespace(title="dinner", kind="event", domain="social",
                              status=None, occurred_at=None, due_at=None,
                              created_at=None, name=None, date=None),
        "record", "both", 0.9,
    )
    out = Responder(fake_backend).run("dinner?", [row], "text")
    assert out == "You had dinner with Nafay."
    assert "phrase" in fake_backend.calls


def test_rows_to_json_projects_record():
    row = RankedRow(
        types.SimpleNamespace(title="pay rent", kind="task", domain="home",
                              status="open", occurred_at=None, due_at=None,
                              created_at=None, name=None, date=None),
        "record", "structured", 0.5,
    )
    d = rows_to_json([row])[0]
    assert d["type"] == "record" and d["title"] == "pay rent" and d["status"] == "open"
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/test_query_respond.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 4: Implement `io_assistant/query/respond.py`**

```python
from __future__ import annotations

import datetime as _dt
import json

from io_assistant.backend.interface import Backend

_EMPTY = "I don't have anything on that yet."


def _iso(v):
    if isinstance(v, _dt.datetime):
        return v.isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    return None


def rows_to_json(rows: list) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        obj = r.obj
        occurs = getattr(r, "occurs_at", None)
        when = _iso(occurs) if occurs is not None else _iso(
            getattr(obj, "occurred_at", None)
            or getattr(obj, "due_at", None)
            or getattr(obj, "date", None)
            or getattr(obj, "created_at", None)
        )
        d = {"type": getattr(r, "target_type", "record"),
             "title": getattr(obj, "title", None) or getattr(obj, "name", None),
             "when": when}
        for attr in ("kind", "domain", "status"):
            v = getattr(obj, attr, None)
            if v is not None:
                d[attr] = v
        out.append(d)
    return out


class Responder:
    def __init__(self, backend: Backend):
        self._backend = backend

    def run(self, question: str, rows: list, shape: str) -> str:
        if not rows:
            return _EMPTY
        return self._backend.phrase(question, rows_to_json(rows), shape)
```

- [ ] **Step 5: Implement `LocalBackend.phrase`** — `io_assistant/backend/local.py`

```python
    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str:
        import json
        return self._chat(
            "You answer strictly from the provided rows.",
            _load_prompt("respond.txt").format(
                question=question, rows=json.dumps(rows, default=str), shape=shape,
            ),
            json_mode=False,
        )
```

- [ ] **Step 6: Implement `AnthropicBackend.phrase`** — `io_assistant/backend/anthropic_backend.py`

```python
    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str:
        return self._complete(
            "You answer strictly from the provided rows.",
            _prompt("respond.txt").format(
                question=question, rows=json.dumps(rows, default=str), shape=shape,
            ),
            max_tokens=800,
        )
```

- [ ] **Step 7: Add backend tests**

`tests/test_backend_local.py`:
```python
def test_local_phrase_returns_text(config, monkeypatch):
    _patch_chat(monkeypatch, "You did leg day yesterday.")
    out = LocalBackend(config).phrase("gym?", [{"title": "leg day"}], "text")
    assert out == "You did leg day yesterday."
```
`tests/test_backend_anthropic.py`:
```python
def test_anthropic_phrase_returns_text(config):
    c = FakeClient("Two tasks are open.")
    out = AnthropicBackend(config, client=c).phrase("work?", [{"title": "x"}], "markdown")
    assert out == "Two tasks are open."
```

- [ ] **Step 8: Run touched tests**

Run: `uv run pytest tests/test_query_respond.py tests/test_backend_local.py tests/test_backend_anthropic.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add io_assistant/query/respond.py io_assistant/prompts/respond.txt io_assistant/backend/ tests/
git commit -m "feat: Responder + LocalBackend/AnthropicBackend phrase() implementations"
```

---

## Task 9: `QueryPipeline` + `Orchestrator` wiring + QUERY end-to-end

**Files:**
- Create: `io_assistant/query/pipeline.py`
- Modify: `io_assistant/orchestrator.py`
- Test: `tests/test_query_pipeline.py`, `tests/test_orchestrator_query.py`
- Docs: `.claude/knowledge/query-pipeline.md`, `.claude/skills/add-query-capability.md`

**Interfaces:**
- Consumes: `Planner`, `resolve_query_entities`, `retrieve_subquery`, `rank`,
  `expand_recurrences`, `Responder`, `EntityResolver`, `Embedder`.
- Produces:
  - `QueryAnswer` (dataclass): `text: str`, `shape: str`, `n_rows: int`.
  - `QueryPipeline(backend, embedder, resolver_cfg)` with
    `answer(self, session, question: str, now: datetime) -> QueryAnswer` —
    1. `plan = Planner(backend).run(question, now)`
    2. for each subquery: `ids = resolve_query_entities(EntityResolver(session, embedder, cfg), session, sq.entities)`; `rows = retrieve_subquery(session, embedder, sq, ids, now)`
    3. `ranked = rank(all_groups, now, top_n=20)`
    4. widest window across subqueries → `expand_recurrences(ranked, lo, hi, now=now)`, then re-sort by `score` and re-cap to 20
    5. `text = Responder(backend).run(question, final_rows, plan.answer_shape)`
    6. return `QueryAnswer(text, plan.answer_shape, len(final_rows))`
  - `Orchestrator`: the `intent == "query"` branch calls a `QueryPipeline`
    (built once in `__init__`), logs the utterance
    (`m.Utterance(text=..., source=..., captured_at=..., resolved_intent="query")`,
    flushed — committed by the existing `handle()` wrapper), and returns
    `HandleResult("query", None, answer.text)`.

- [ ] **Step 1: Write the failing pipeline test** — `tests/test_query_pipeline.py`

```python
import datetime as dt

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.query.pipeline import QueryPipeline

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)


def _stub_embedder(monkeypatch):
    import io_assistant.query.pipeline as p
    monkeypatch.setattr(p, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())


@requires_db
def test_pipeline_answers_from_stored_record(db, config, fake_backend, monkeypatch):
    _stub_embedder(monkeypatch)
    u = m.Utterance(text="dinner with Nafay", source="text", captured_at=NOW)
    db.add(u); db.flush()
    p = m.Person(canonical_name="Nafay", aliases=[]); db.add(p); db.flush()
    r = m.Record(kind="event", domain="social", title="dinner with Nafay",
                 occurred_at=NOW - dt.timedelta(days=2), attributes={},
                 source_utterance_id=u.id)
    db.add(r); db.flush()
    db.add(m.RecordPerson(record_id=r.id, person_id=p.id)); db.flush()

    fake_backend.set_plan({
        "subqueries": [{"target_type": "record", "kind_filter": ["event"],
                        "entities": ["Nafay"],
                        "time_window": {"start": "last week", "end": "today"}}],
        "answer_shape": "text",
    })
    fake_backend.set_answer("You had dinner with Nafay two days ago.")

    pipe = QueryPipeline(fake_backend, None, config.resolver)
    ans = pipe.answer(db, "when did I last see Nafay?", NOW)
    assert ans.n_rows == 1
    assert "Nafay" in ans.text
```

- [ ] **Step 2: Write the failing Orchestrator test** — `tests/test_orchestrator_query.py`

```python
import datetime as dt

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 8, 12, 0, tzinfo=dt.timezone.utc)


def _stub_embedders(monkeypatch):
    stub = type("E", (), {"embed_one": lambda self, t: [0.0] * 768,
                          "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})
    import io_assistant.orchestrator as o
    import io_assistant.query.pipeline as p
    monkeypatch.setattr(o, "Embedder", lambda cfg: stub())
    monkeypatch.setattr(p, "Embedder", lambda cfg: stub())


@requires_db
def test_query_intent_answers_and_logs(db, config, fake_backend, monkeypatch):
    _stub_embedders(monkeypatch)
    u = m.Utterance(text="x", source="text", captured_at=NOW); db.add(u); db.flush()
    db.add(m.Record(kind="task", domain="job", title="finish the report",
                    status="open", due_at=NOW, attributes={},
                    source_utterance_id=u.id)); db.flush()

    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [{"target_type": "record",
                          "domain_filter": ["job"], "status_filter": ["open"]}],
                          "answer_shape": "markdown"})
    fake_backend.set_answer("- finish the report (due today)")

    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = o.handle("what work do I have today?", captured_at=NOW)
    assert res.intent == "query"
    assert "report" in res.message
    assert db.query(m.Utterance).filter_by(resolved_intent="query").count() == 1
```

- [ ] **Step 3: Run to verify both fail**

Run: `uv run pytest tests/test_query_pipeline.py tests/test_orchestrator_query.py -v`
Expected: FAIL — no `QueryPipeline`; Orchestrator still returns the "not
available" stub.

- [ ] **Step 4: Implement `io_assistant/query/pipeline.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from io_assistant.backend.embed import Embedder
from io_assistant.config import ResolverConfig
from io_assistant.query.entities import resolve_query_entities
from io_assistant.query.planner import Planner
from io_assistant.query.rank import rank
from io_assistant.query.recur import expand_recurrences
from io_assistant.query.respond import Responder
from io_assistant.query.retrieve import retrieve_subquery
from io_assistant.resolve.resolver import EntityResolver

_TOP_N = 20


@dataclass
class QueryAnswer:
    text: str
    shape: str
    n_rows: int


class QueryPipeline:
    def __init__(self, backend, embedder, resolver_cfg: ResolverConfig):
        self._backend = backend
        self._embedder = embedder
        self._cfg = resolver_cfg

    def _embed(self):
        return self._embedder if self._embedder is not None else Embedder.__new__(Embedder)

    def answer(self, session, question: str, now: datetime) -> QueryAnswer:
        embedder = self._embedder
        plan = Planner(self._backend).run(question, now)

        groups = []
        starts, ends = [], []
        for sq in plan.subqueries:
            resolver = EntityResolver(session, embedder, self._cfg)
            ids = resolve_query_entities(resolver, session, sq.entities)
            groups.append(retrieve_subquery(session, embedder, sq, ids, now))
            if sq.time_window is not None:
                starts.append(sq.time_window.start)
                ends.append(sq.time_window.end)

        ranked = rank(groups, now, top_n=_TOP_N)

        lo = min((s for s in starts if s is not None), default=None)
        hi = max((e for e in ends if e is not None), default=None)
        expanded = expand_recurrences(ranked, lo, hi, now=now)
        expanded.sort(key=lambda r: r.score, reverse=True)
        final = expanded[:_TOP_N]

        text = Responder(self._backend).run(question, final, plan.answer_shape)
        return QueryAnswer(text, plan.answer_shape, len(final))
```

(Note: `_embed` helper above is unused — delete it; `answer` uses
`self._embedder` directly. The pipeline always receives a real `Embedder` from
the Orchestrator; tests inject a stub or pass one explicitly.)

- [ ] **Step 5: Wire the Orchestrator** — `io_assistant/orchestrator.py`

Import and build the pipeline in `__init__`:
```python
from io_assistant.query.pipeline import QueryPipeline
...
        self._embedder = Embedder(config)
        self._router = Router(self._backend)
        self._extractor = Extractor(self._backend)
        self._query = QueryPipeline(self._backend, self._embedder, config.resolver)
```
Replace the `intent == "query"` branch in `_handle_in_session`:
```python
        if intent == "query":
            session.add(m.Utterance(
                text=text, source=source, captured_at=captured_at,
                resolved_intent="query",
            ))
            session.flush()
            answer = self._query.answer(session, text, now)
            return HandleResult("query", None, answer.text)
```
(`captured_at`/`now` are already resolved above the intent checks — confirm the
`if captured_at is None` block runs before this branch; move it up if needed.)

- [ ] **Step 6: Run to verify both pass**

Run: `uv run pytest tests/test_query_pipeline.py tests/test_orchestrator_query.py -v`
Expected: PASS.

- [ ] **Step 7: Update the knowledge docs**

- `.claude/knowledge/query-pipeline.md`: change the header note from
  "Implemented in Plan 2 — not built in Plan 1" to "Implemented (Plan 2,
  2026-09-08)"; add the module map (`io_assistant/query/*`) and the ranking
  weights.
- `.claude/skills/add-query-capability.md`: replace the "Plan 2" placeholder
  with the real checklist — add a `target_type` or filter → extend
  `SubQuery` + `plan.txt` → `compile.py` branch → `retrieve.py` if a new table
  → `rank.py` recency column → fixture in `questions_plan.json` → tests.

- [ ] **Step 8: Full suite**

Run: `uv run pytest -q`
Expected: PASS (no regressions; new query tests green).

- [ ] **Step 9: Commit**

```bash
git add io_assistant/query/pipeline.py io_assistant/orchestrator.py tests/ .claude/
git commit -m "feat: QueryPipeline wired into Orchestrator; QUERY path end-to-end"
```

---

## Task 10: End-to-end spec scenarios (2 & 3) against a stub backend

**Files:**
- Test: `tests/test_e2e_query.py`

**Interfaces:**
- Consumes: the whole pipeline + `Orchestrator`.
- Produces: two `@requires_db` tests proving spec §9 scenarios 2 and 3 through
  the real `Orchestrator.handle` with a `FakeBackend` scripted per step. No new
  production code — if a scenario fails, fix the pipeline, not the test.

- [ ] **Step 1: Write the tests** — `tests/test_e2e_query.py`

```python
import datetime as dt

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedRecord)
from io_assistant.db import models as m

STORE_DAY = dt.datetime(2026, 9, 1, 19, 0, tzinfo=dt.timezone.utc)
QUERY_DAY = dt.datetime(2026, 9, 8, 9, 0, tzinfo=dt.timezone.utc)


def _stub_embedders(monkeypatch):
    stub = type("E", (), {"embed_one": lambda self, t: [0.0] * 768,
                          "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})
    import io_assistant.orchestrator as o
    import io_assistant.query.pipeline as p
    monkeypatch.setattr(o, "Embedder", lambda cfg: stub())
    monkeypatch.setattr(p, "Embedder", lambda cfg: stub())


@requires_db
def test_scenario_2_hangout_with_nafay(db, config, fake_backend, monkeypatch):
    _stub_embedders(monkeypatch)
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)

    fake_backend.set_intent("store")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)],
        places=[ExtractedPlace(name="Arcadian", confidence=0.9)],
        records=[ExtractedRecord(kind="event", domain="social",
                                 title="dinner with Nafay at Arcadian",
                                 when_phrase="today", people=["Nafay"],
                                 places=["Arcadian"], confidence=0.9)]))
    o.handle("went out with Nafay to eat at Arcadian", captured_at=STORE_DAY)

    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [{"target_type": "record",
                          "kind_filter": ["event"], "entities": ["Nafay"],
                          "time_window": {"start": "last week", "end": "today"}}],
                          "answer_shape": "text"})
    fake_backend.set_answer("You had dinner with Nafay at Arcadian on Sep 1.")
    res = o.handle("Where have I hung out with Nafay in the past week?",
                   captured_at=QUERY_DAY)
    assert res.intent == "query" and "Nafay" in res.message


@requires_db
def test_scenario_3_what_work_today(db, config, fake_backend, monkeypatch):
    _stub_embedders(monkeypatch)
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    fake_backend.set_intent("store")

    for title, kind, domain, rec_phrase in [
        ("email the landlord", "task", "home", None),
        ("finish the Q3 deck", "task", "job", None),
        ("take out the trash", "chore", "home", "every Tuesday"),
    ]:
        fake_backend.set_extraction(ExtractionResult(records=[ExtractedRecord(
            kind=kind, domain=domain, title=title, status="open",
            recurrence_phrase=rec_phrase,
            when_phrase=None if rec_phrase else "today", confidence=0.9)]))
        o.handle(f"note: {title}", captured_at=QUERY_DAY)

    fake_backend.set_intent("query")
    fake_backend.set_plan({"subqueries": [
        {"target_type": "record", "domain_filter": ["job"], "status_filter": ["open"],
         "time_window": {"start": None, "end": "today"}},
        {"target_type": "record", "kind_filter": ["chore"], "status_filter": ["open"]},
    ], "answer_shape": "markdown"})
    fake_backend.set_answer("- finish the Q3 deck\n- take out the trash")
    res = o.handle("What work do I have today?", captured_at=QUERY_DAY)
    assert res.intent == "query"
    assert "deck" in res.message and "trash" in res.message
```

- [ ] **Step 2: Run**

Run: `uv run pytest tests/test_e2e_query.py -v`
Expected: PASS. If scenario 3's chore doesn't surface, check that
`expand_recurrences` runs with `hi = now` when a subquery has no window and the
chore has `recurrence_rule = "FREQ=WEEKLY;BYDAY=TU"` anchored at `created_at`.

- [ ] **Step 3: Full suite + local-first guard**

Run: `uv run pytest -q`
Expected: PASS. Confirm `tests/test_e2e_store.py`'s socket guard still passes
(the query pipeline opens no non-local sockets — embeddings go through the same
local `Embedder`).

- [ ] **Step 4: Commit**

```bash
git add tests/test_e2e_query.py
git commit -m "test: QUERY end-to-end spec scenarios 2 and 3"
```

---

## Self-Review

**Spec coverage (§5):**
- §5.1 Plan → Task 1 (`ground_plan`, clamping) + Task 2 (`Planner`, backend).
  "Time windows and kind/domain vocabulary grounded/clamped by app code" →
  `ground_plan` (`normalize_kind`/`normalize_domain`/`ground`).
- §5.2 Retrieve both paths → Task 4 (structured spine) + Task 5 (semantic NN
  bounded by target type + time window, union with provenance).
- §5.3 Merge & rank → Task 6 (recency, similarity, structured relevance,
  provenance bonus; top-N = 20).
- §5.4 Expand recurrences → Task 7 (`dateutil.rrule`, window-bounded, cap 50).
- §5.5 Phrase → Task 8 (`respond.txt`, shape handling, "nothing matched"
  deterministic).
- §5.6 Efficiency → every retrieval bounded by target type; semantic capped at
  50, structured at 200, final at 20; HNSW/b-tree/trgm indexes from Plans 1–2.
- §2 data flow QUERY branch + §9 scenarios 2 & 3 → Task 9 + Task 10.

**LLM-boundary check:** the model returns a dict (`plan`) or prose (`phrase`)
only. `ground_plan` (deterministic) owns dates and vocab; `compile.py` owns SQL;
`rank.py` owns ranking; `EntityResolver` owns identity. No task lets a model
output reach the database as SQL or a filter value un-clamped.

**Not in Plan 2 (deferred):** `aggregation` (`count`/`latest`) is parsed and
carried on `SubQuery` but not yet special-cased in `compile.py` — every
subquery currently returns a row list and the Responder does any counting from
the rows. A follow-up can push `count`/`latest` into SQL. Recorded in
`.claude/state/backlog.md` at execution time.

**Placeholder scan:** none — every step has literal code or an exact command.
The one acknowledged loose end (`QueryPipeline._embed` helper) is called out in
Task 9 Step 4 with the instruction to delete it.

**Type consistency:**
- `SubQuery` / `QueryPlan` / `TimeWindow` fields identical across Tasks 1, 2, 4,
  5, 9.
- `RetrievedRow` (obj, target_type, provenance, distance) used in Tasks 5, 6.
- `RankedRow` (obj, target_type, provenance, score, components) used in Tasks 6,
  7, 8, 9.
- `entity_ids` dict shape `{"person"|"place"|"item"|"occasion": [int]}` produced
  by Task 3, consumed by Tasks 4, 5, 9.
- `Backend.plan -> dict`, `Backend.phrase -> str` — consistent in interface,
  local, anthropic, FakeBackend across Tasks 2, 8.

---

## Execution Handoff

Plan complete. Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, review between.
   Task order: 1 → 2 → 3 → (4 depends on 1+3) → 5 (needs 4) → 6 (needs 5) →
   7 (needs 6) → 8 → 9 (needs 2,3,5,6,7,8) → 10.
2. **Inline Execution** — `superpowers:executing-plans`, batched with checkpoints.
