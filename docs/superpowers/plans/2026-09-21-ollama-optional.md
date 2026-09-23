# Ollama-optional Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** IO runs completely on an Anthropic API key with no Ollama installed, without changing behaviour when Ollama is present.

**Architecture:** `Embedder` becomes a chain: Ollama first (when reachable), else an in-process `fastembed` model that is the same `nomic-embed-text-v1.5` (768-d, vector-compatible). If neither works, call sites degrade to the existing fuzzy/`pg_trgm` matching via `embed_or_none`, and a daemon thread backfills NULL embeddings later. Startup scripts and `io doctor` stop treating Ollama as required.

**Tech Stack:** Python 3.11, `fastembed` (ONNX), SQLAlchemy + pgvector, pytest against real Postgres (`IO_TEST_DATABASE_URL`), PowerShell.

**Spec:** `docs/superpowers/specs/2026-09-21-ollama-optional-design.md`

## Global Constraints

- Tests run against real PostgreSQL; never mock the database. Embedder/backends may be faked (`tests/conftest.py`).
- Everything through `uv run`. Test command: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run pytest -q -p no:warnings`
- `embedding_dim` stays 768; no migration in this plan (rules/migrations.md is not triggered because the model and dimension do not change).
- Local-first: the only new outbound call is the one-time HuggingFace model download, only for the built-in embedder.
- `LocalBackend` (provider `local`) behaviour must not change.
- Existing tests in `tests/test_embed.py` must keep passing unchanged.

---

## File structure

| File | Responsibility |
|---|---|
| `io_assistant/config.py` (modify) | `BackendConfig.embedder`, `builtin_embed_model`, `models_dir` |
| `io_assistant/backend/embed.py` (modify) | `Embedder` chain, `OllamaUnavailable`, `embed_or_none` |
| `io_assistant/backend/embed_builtin.py` (create) | `BuiltinEmbedder` (fastembed wrapper) |
| `io_assistant/backend/backfill.py` (create) | `backfill_embeddings`, `EmbeddingBackfiller` thread |
| `io_assistant/resolve/resolver.py`, `query/retrieve.py`, `persist/writer.py`, `files/caption.py`, `files/search.py` (modify) | use `embed_or_none`, skip vector branch on `None` |
| `io_assistant/service/app.py` (modify) | start the backfiller |
| `io_assistant/doctor.py`, `io_assistant/cli.py` (modify) | embedder-aware check, `--fetch-embedder` |
| `dev.ps1`, `scripts/setup.ps1` (modify) | Ollama only when needed |
| `.claude/rules/local-first.md`, `.claude/knowledge/model-backends.md`, `.claude/skills/run-local.md` (modify) | document the new path |

---

### Task 1: Embedder chain with lexical-safe helper

**Files:**
- Modify: `io_assistant/config.py` (class `BackendConfig`, ~line 17)
- Modify: `io_assistant/backend/embed.py` (whole file)
- Test: `tests/test_embed.py` (append)

**Interfaces:**
- Produces: `BackendConfig.embedder: Literal["auto","ollama","builtin"] = "auto"`, `BackendConfig.builtin_embed_model: str = "nomic-ai/nomic-embed-text-v1.5"`, `BackendConfig.models_dir: str = "~/.local/share/io/models"`.
- Produces: `Embedder(config, *, builtin=None, clock=time.monotonic)` with unchanged `embed(texts) -> list[list[float]]` / `embed_one(text) -> list[float]`; `class OllamaUnavailable(EmbedError)`; `embed_or_none(embedder, text) -> list[float] | None`.
- Consumes (lazy, Task 2): `io_assistant.backend.embed_builtin.BuiltinEmbedder(config)` with `.embed(texts)`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_embed.py`:

```python
class _Builtin:
    def __init__(self):
        self.calls = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[0.5] * 768 for _ in texts]


def _refuse(monkeypatch, hits=None):
    class Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            if hits is not None:
                hits.append(1)
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "Client", Client)


def test_auto_falls_back_to_builtin_when_ollama_down(config, monkeypatch):
    _refuse(monkeypatch)
    b = _Builtin()
    out = Embedder(config, builtin=b).embed(["a"])
    assert out == [[0.5] * 768]
    assert b.calls == [["a"]]


def test_auto_skips_ollama_for_a_minute_after_failure(config, monkeypatch):
    hits = []
    _refuse(monkeypatch, hits)
    now = [0.0]
    e = Embedder(config, builtin=_Builtin(), clock=lambda: now[0])
    e.embed(["a"])
    e.embed(["b"])
    assert len(hits) == 1
    now[0] = 61.0
    e.embed(["c"])
    assert len(hits) == 2


def test_builtin_mode_never_calls_ollama(config, monkeypatch):
    config.backend.embedder = "builtin"
    hits = []
    _refuse(monkeypatch, hits)
    Embedder(config, builtin=_Builtin()).embed(["a"])
    assert hits == []


def test_ollama_mode_has_no_fallback(config, monkeypatch):
    config.backend.embedder = "ollama"
    _refuse(monkeypatch)
    b = _Builtin()
    with pytest.raises(EmbedError):
        Embedder(config, builtin=b).embed(["a"])
    assert b.calls == []


def test_builtin_failure_raises_and_is_remembered(config, monkeypatch):
    _refuse(monkeypatch)
    calls = []

    class Broken:
        def embed(self, texts):
            calls.append(1)
            raise EmbedError("model missing")

    now = [0.0]
    e = Embedder(config, builtin=Broken(), clock=lambda: now[0])
    with pytest.raises(EmbedError):
        e.embed(["a"])
    with pytest.raises(EmbedError):
        e.embed(["b"])
    assert len(calls) == 1   # second call short-circuits inside the retry window


def test_embed_or_none_swallows_embed_error():
    from io_assistant.backend.embed import embed_or_none

    class Down:
        def embed_one(self, t):
            raise EmbedError("down")

    assert embed_or_none(Down(), "x") is None

    class Up:
        def embed_one(self, t):
            return [1.0]

    assert embed_or_none(Up(), "x") == [1.0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_embed.py -q -p no:warnings`
Expected: the 6 new tests FAIL (`unexpected keyword 'builtin'` / `cannot import embed_or_none`); the 2 old ones pass.

- [ ] **Step 3: Add the config fields** — in `io_assistant/config.py`, inside `BackendConfig`, after `num_thread: int`:

```python
    # "auto": Ollama when reachable, else the in-process fastembed model (same
    # nomic-embed-text v1.5, 768-d, so vectors are interchangeable).
    embedder: Literal["auto", "ollama", "builtin"] = "auto"
    builtin_embed_model: str = "nomic-ai/nomic-embed-text-v1.5"
    models_dir: str = "~/.local/share/io/models"
```

- [ ] **Step 4: Rewrite `io_assistant/backend/embed.py`**

```python
from __future__ import annotations

import logging
import time

import httpx

from io_assistant.config import Config

log = logging.getLogger(__name__)

# after a failure, don't retry that embedder for this long (avoids a slow
# connect / model-load attempt on every single embed call)
_RETRY_S = 60.0


class EmbedError(Exception):
    pass


class OllamaUnavailable(EmbedError):
    """Ollama couldn't be reached or refused the request (not a data error)."""


class Embedder:
    def __init__(self, config: Config, *, builtin=None, clock=time.monotonic):
        b = config.backend
        self._config = config
        self._url = b.ollama_url.rstrip("/") + "/api/embed"
        self._model = b.embed_model
        self._dim = config.embedding_dim
        self._keep_alive = b.ollama_keep_alive
        self._mode = b.embedder
        self._builtin = builtin
        self._clock = clock
        self._ollama_down_until = 0.0
        self._builtin_down_until = 0.0

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._mode == "ollama":
            return self._embed_ollama(texts)
        if self._mode == "auto" and self._clock() >= self._ollama_down_until:
            try:
                return self._embed_ollama(texts)
            except OllamaUnavailable as e:
                log.info("Ollama unavailable, using built-in embedder: %s", e)
                self._ollama_down_until = self._clock() + _RETRY_S
        return self._embed_builtin(texts)

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    self._url,
                    json={
                        "model": self._model,
                        "input": texts,
                        "keep_alive": self._keep_alive,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPError as e:
            raise OllamaUnavailable(f"ollama embed failed: {e}") from e
        return self._check(data.get("embeddings") or [], texts)

    def _embed_builtin(self, texts: list[str]) -> list[list[float]]:
        if self._clock() < self._builtin_down_until:
            raise EmbedError("built-in embedder unavailable (retrying shortly)")
        if self._builtin is None:
            from io_assistant.backend.embed_builtin import BuiltinEmbedder

            self._builtin = BuiltinEmbedder(self._config)
        try:
            return self._builtin.embed(texts)
        except EmbedError:
            self._builtin_down_until = self._clock() + _RETRY_S
            raise

    def _check(self, vecs, texts) -> list[list[float]]:
        if len(vecs) != len(texts):
            raise EmbedError(f"expected {len(texts)} vectors, got {len(vecs)}")
        for v in vecs:
            if len(v) != self._dim:
                raise EmbedError(
                    f"embedding dim {len(v)} != configured {self._dim}"
                )
        return vecs


def embed_or_none(embedder, text: str) -> list[float] | None:
    """Vector for `text`, or None when no embedder is available — callers fall
    back to lexical matching and leave the column NULL for the backfill."""
    try:
        return embedder.embed_one(text)
    except EmbedError as e:
        log.warning("embeddings unavailable, continuing without a vector: %s", e)
        return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_embed.py -q -p no:warnings`
Expected: 8 passed (2 old + 6 new; the opt-in Ollama test is skipped so 8 passed, 1 skipped).

- [ ] **Step 6: Commit**

```bash
git add io_assistant/config.py io_assistant/backend/embed.py tests/test_embed.py
git commit -m "feat(embed): Ollama-or-builtin embedder chain + embed_or_none"
```

---

### Task 2: Built-in fastembed embedder

**Files:**
- Modify: `pyproject.toml` (add dependency; add pytest marker)
- Create: `io_assistant/backend/embed_builtin.py`
- Modify: `packaging/io.spec` (hidden imports)
- Modify: `docs/superpowers/specs/2026-09-21-ollama-optional-design.md` (size correction)
- Test: `tests/test_embed_builtin.py`

**Interfaces:**
- Consumes: `EmbedError` from `io_assistant.backend.embed`; `_resolve_threads(n) -> int` from `io_assistant.backend.local`; `BackendConfig.builtin_embed_model` / `models_dir`.
- Produces: `BuiltinEmbedder(config)` with `.embed(texts) -> list[list[float]]` (raises `EmbedError`).

- [ ] **Step 1: Add the dependency**

Run: `uv add fastembed`
Expected: `pyproject.toml` gains `"fastembed>=..."` and `uv.lock` updates. Then add to `markers` in `pyproject.toml`:

```toml
    "builtin: requires downloading the fastembed model (set IO_BUILTIN_EMBED_TESTS=1)",
```

- [ ] **Step 2: Write the failing tests** — create `tests/test_embed_builtin.py`:

```python
import os
import sys
import types

import pytest

from io_assistant.backend.embed import EmbedError
from io_assistant.backend.embed_builtin import BuiltinEmbedder


class Vec(list):
    def tolist(self):
        return list(self)


def _embedder(config, vec_len):
    b = BuiltinEmbedder(config)
    b._model = types.SimpleNamespace(
        embed=lambda texts: iter([Vec([0.1] * vec_len) for _ in texts])
    )
    return b


def test_returns_vectors_of_configured_dimension(config):
    out = _embedder(config, 768).embed(["a", "b"])
    assert len(out) == 2 and len(out[0]) == 768


def test_wrong_dimension_raises(config):
    with pytest.raises(EmbedError):
        _embedder(config, 10).embed(["a"])


def test_missing_library_raises_embed_error(config, monkeypatch):
    monkeypatch.setitem(sys.modules, "fastembed", None)  # import -> ImportError
    with pytest.raises(EmbedError):
        BuiltinEmbedder(config).embed(["a"])


@pytest.mark.builtin
@pytest.mark.skipif(os.environ.get("IO_BUILTIN_EMBED_TESTS") != "1", reason="opt-in (downloads ~520 MB)")
def test_real_model_dimension(config):
    v = BuiltinEmbedder(config).embed(["hello world"])[0]
    assert len(v) == config.embedding_dim


@pytest.mark.builtin
@pytest.mark.ollama
@pytest.mark.skipif(
    os.environ.get("IO_BUILTIN_EMBED_TESTS") != "1" or os.environ.get("IO_OLLAMA_TESTS") != "1",
    reason="opt-in (needs the model and a running Ollama)",
)
def test_builtin_matches_ollama(config):
    from io_assistant.backend.embed import Embedder

    config.backend.embedder = "ollama"
    ollama = Embedder(config).embed_one("Nafay and Eelian's birthday")
    builtin = BuiltinEmbedder(config).embed(["Nafay and Eelian's birthday"])[0]
    dot = sum(a * b for a, b in zip(ollama, builtin))
    na = sum(a * a for a in ollama) ** 0.5
    nb = sum(b * b for b in builtin) ** 0.5
    assert dot / (na * nb) > 0.98
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_embed_builtin.py -q -p no:warnings`
Expected: collection error / FAIL — `No module named 'io_assistant.backend.embed_builtin'`.

- [ ] **Step 4: Implement** — create `io_assistant/backend/embed_builtin.py`:

```python
"""In-process embedder so IO needs no Ollama. fastembed runs the same
nomic-embed-text v1.5 as Ollama's `nomic-embed-text`, so its 768-d vectors are
interchangeable with ones already stored. The model (~520 MB fp32) downloads
once from HuggingFace into config.backend.models_dir — see rules/local-first.md."""
from __future__ import annotations

import os

from io_assistant.backend.embed import EmbedError
from io_assistant.backend.local import _resolve_threads
from io_assistant.config import Config


class BuiltinEmbedder:
    def __init__(self, config: Config):
        b = config.backend
        self._name = b.builtin_embed_model
        self._cache = os.path.expanduser(b.models_dir)
        self._threads = _resolve_threads(b.num_thread)
        self._dim = config.embedding_dim
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(
                    model_name=self._name,
                    cache_dir=self._cache,
                    threads=self._threads,
                )
            except Exception as e:  # noqa: BLE001 — ImportError, download, ONNX
                raise EmbedError(f"built-in embedder unavailable: {e}") from e
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        try:
            vecs = [v.tolist() for v in model.embed(texts)]
        except Exception as e:  # noqa: BLE001
            raise EmbedError(f"built-in embed failed: {e}") from e
        for v in vecs:
            if len(v) != self._dim:
                raise EmbedError(
                    f"embedding dim {len(v)} != configured {self._dim}"
                )
        return vecs
```

- [ ] **Step 5: Packaging + spec correction**

In `packaging/io.spec`, add `"fastembed", "tokenizers", "huggingface_hub"` to `_VOICE_HIDDEN`'s neighbouring list (add a new `_EMBED_HIDDEN = ["fastembed", "tokenizers", "huggingface_hub"]` and append it wherever `_VOICE_HIDDEN` is added to `HIDDEN_IMPORTS`; grep `_VOICE_HIDDEN` for the join site).

In the spec, replace "~130 MB model download" / "(~130 MB)" with "~520 MB (fp32) model download" and add under design item 1: "`builtin_embed_model` may be set to `nomic-ai/nomic-embed-text-v1.5-Q` (~130 MB) to trade fidelity for size."

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_embed_builtin.py tests/test_embed.py -q -p no:warnings`
Expected: 10 passed, 3 skipped (opt-in). Then, once, run the real checks: `IO_BUILTIN_EMBED_TESTS=1 uv run pytest tests/test_embed_builtin.py -k real -q` (downloads the model). If Ollama is available also `IO_BUILTIN_EMBED_TESTS=1 IO_OLLAMA_TESTS=1 uv run pytest tests/test_embed_builtin.py -k matches -q`. If cosine ≤ 0.98, stop and report — the compatibility assumption is wrong.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock io_assistant/backend/embed_builtin.py packaging/io.spec docs/superpowers/specs/2026-09-21-ollama-optional-design.md tests/test_embed_builtin.py
git commit -m "feat(embed): in-process fastembed nomic-v1.5 embedder"
```

---

### Task 3: Lexical fallback at every vector call site

**Files:**
- Modify: `io_assistant/resolve/resolver.py` (lines 111-127, 149-160, 165)
- Modify: `io_assistant/query/retrieve.py` (lines 81-98)
- Modify: `io_assistant/persist/writer.py` (lines 230, 280)
- Modify: `io_assistant/files/caption.py` (lines 109, 116)
- Modify: `io_assistant/files/search.py` (lines 86-99)
- Test: `tests/test_embedding_fallback.py`

**Interfaces:**
- Consumes: `embed_or_none(embedder, text) -> list[float] | None`, `EmbedError` (Task 1).
- Produces: behaviour — with an embedder that raises `EmbedError`, `EntityResolver.resolve/lookup/create`, `retrieve_subquery`, `persist_store`, `FileSearcher` search, and `apply_caption` complete without raising; new rows have `embedding IS NULL`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_embedding_fallback.py`:

```python
import datetime as dt

from tests.conftest import requires_db
from io_assistant.backend.embed import EmbedError
from io_assistant.db import models as m
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedRecord)
from io_assistant.persist.writer import persist_store
from io_assistant.query.plan import SubQuery
from io_assistant.query.retrieve import retrieve_subquery
from io_assistant.resolve.resolver import EntityResolver

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.timezone.utc)
EMPTY = {"person": [], "place": [], "item": [], "occasion": []}


class DownEmbedder:
    def embed_one(self, t):
        raise EmbedError("no embedder")

    def embed(self, ts):
        raise EmbedError("no embedder")


@requires_db
def test_resolver_create_and_exact_match_work_without_embedder(db, config):
    r = EntityResolver(db, DownEmbedder(), config.resolver)
    pid = r.create("person", "Nafay", [])
    assert db.get(m.Person, pid).embedding is None
    out = r.resolve("person", "nafay", [])       # exact, case-insensitive
    assert out.entity_id == pid and not out.is_new


@requires_db
def test_resolver_unknown_name_is_new_without_embedder(db, config):
    r = EntityResolver(db, DownEmbedder(), config.resolver)
    out = r.resolve("person", "Zebulon Quux", [])
    assert out.is_new and out.entity_id is None


@requires_db
def test_lookup_falls_back_to_fuzzy_without_embedder(db, config):
    r = EntityResolver(db, DownEmbedder(), config.resolver)
    pid = r.create("person", "Eelian Hart", [])
    assert r.lookup("person", "Eelian Hart") == pid
    assert r.lookup("person", "Qwertyuiop") is None


@requires_db
def test_retrieve_semantic_branch_skipped_without_embedder(db):
    u = m.Utterance(text="s", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    db.add(m.Record(kind="note", title="gym leg day", occurred_at=NOW,
                    attributes={}, source_utterance_id=u.id))
    db.flush()
    sq = SubQuery(target_type="record", kind_filter=["note"], semantic_hint="workout")
    rows = retrieve_subquery(db, DownEmbedder(), sq, EMPTY, NOW)
    assert [r.obj.title for r in rows] == ["gym leg day"]   # structured spine only
    assert all(r.provenance == "structured" for r in rows)


@requires_db
def test_persist_store_writes_null_embeddings_without_embedder(db, config):
    emb = DownEmbedder()
    res = persist_store(
        db, emb, EntityResolver(db, emb, config.resolver),
        utterance_text="lunch with Nafay", source="text", captured_at=NOW,
        extraction=ExtractionResult(
            people=[ExtractedPerson(name="Nafay", confidence=0.95)],
            records=[ExtractedRecord(kind="event", title="lunch with Nafay",
                                     people=["Nafay"], confidence=0.9)]),
        now=NOW, confidence_gate=0.6)
    assert res is not None
    rec = db.query(m.Record).filter_by(title="lunch with Nafay").one()
    assert rec.embedding is None
    assert db.query(m.Person).filter_by(canonical_name="Nafay").one().embedding is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run pytest tests/test_embedding_fallback.py -q -p no:warnings`
Expected: 5 FAIL with `EmbedError: no embedder`. (Needs Docker Postgres up — start it with `.\dev.ps1 up -NoWindow` or `docker compose up -d db`.)

- [ ] **Step 3: Resolver** — in `io_assistant/resolve/resolver.py` add `from io_assistant.backend.embed import embed_or_none` to the imports, then:

Replace lines 111-127 (`# 3. vector …` through `return ResolveOutcome(None, True, False, None, None)`) with:

```python
        # 3. vector: cosine search, similarity = 1 - distance (skipped when no
        #    embedder is available — exact + fuzzy above are the lexical path)
        vec = embed_or_none(self.embedder, name)
        if vec is not None:
            dist = model.embedding.cosine_distance(vec).label("dist")
            vstmt = (
                select(model.id, name_col, dist)
                .where(model.embedding.isnot(None))
                .order_by(dist.asc())
                .limit(1)
            )
            vrow = self.session.execute(vstmt).first()
            if vrow is not None:
                similarity = 1.0 - float(vrow[2])
                if similarity >= self.cfg.vector_similarity_threshold:
                    return ResolveOutcome(None, False, True, vrow[0], vrow[1])

        # 4. none
        return ResolveOutcome(None, True, False, None, None)
```

Replace lines 149-160 (`model, _name_col = … return None`) with:

```python
        vec = embed_or_none(self.embedder, name)
        if vec is None:
            return None
        model, _name_col = self._model_col(entity_type)
        dist = model.embedding.cosine_distance(vec).label("dist")
        row = self.session.execute(
            select(model.id, dist)
            .where(model.embedding.isnot(None))
            .order_by(dist.asc())
            .limit(1)
        ).first()
        if row is not None and (1.0 - float(row[1])) >= self.cfg.vector_similarity_threshold:
            return row[0]
        return None
```

Change line 165 to `obj.embedding = embed_or_none(self.embedder, name)`.

- [ ] **Step 4: Retrieve** — in `io_assistant/query/retrieve.py` add `from io_assistant.backend.embed import embed_or_none`; replace lines 81-98 with:

```python
    vec = embed_or_none(embedder, sq.semantic_hint) if sq.semantic_hint else None
    if vec is not None:
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
```

- [ ] **Step 5: Writer, caption, file search**

`io_assistant/persist/writer.py`: add `from io_assistant.backend.embed import embed_or_none`; line 230 → `obj.embedding = embed_or_none(embedder, occ.name)`; lines 280-282 →
```python
        row.embedding = embed_or_none(
            embedder, (rec.title + "\n" + (rec.body or "")).strip()
        )
```
`io_assistant/files/caption.py`: add the same import; line 109 → `obj.embedding = embed_or_none(embedder, occ.name)`; line 116 → `node.embedding = embed_or_none(embedder, text)`.
`io_assistant/files/search.py`: add `from io_assistant.backend.embed import embed_or_none`; replace the `# 1b semantic` block (lines 86-99) with the same code guarded:
```python
        # 1b semantic (skipped when no embedder is available)
        qvec = embed_or_none(self._embed, question)
        if qvec is not None:
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
```
`files/index.py` is deliberately unchanged: `file_chunks.embedding` is NOT NULL, so indexing raises `EmbedError`, which `IndexQueue._run` already catches (queue.py:58) and moves on; files are indexed once an embedder is available.

- [ ] **Step 6: Run tests to verify they pass, then the full suite**

Run: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test' uv run pytest tests/test_embedding_fallback.py -q -p no:warnings` → 5 passed.
Then: `IO_TEST_DATABASE_URL=… uv run pytest -q -p no:warnings --deselect tests/test_service_standby.py::test_standby_panel` → expected all pass except tests needing live Ollama (`test_orchestrator_files.py` — see Task 5 step 6).

- [ ] **Step 7: Commit**

```bash
git add io_assistant tests/test_embedding_fallback.py
git commit -m "feat(embed): lexical fallback at all vector call sites"
```

---

### Task 4: Embedding backfill thread

**Files:**
- Create: `io_assistant/backend/backfill.py`
- Modify: `io_assistant/service/app.py` (after the tracker poller block, ~line 390)
- Test: `tests/test_backfill.py`

**Interfaces:**
- Consumes: `EmbedError`; `m.Person.canonical_name`, `m.Place.name`, `m.Item.name`, `m.Occasion.name`, `m.Record.title/body`.
- Produces: `backfill_embeddings(session, embedder, *, batch=32) -> int` (rows filled; stops at the first `EmbedError`, returning the count so far); `EmbeddingBackfiller(session_factory, embedder, *, tick_s=300)` with `.start()`, `.stop()`, `.run_once() -> int`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_backfill.py`:

```python
import datetime as dt

from tests.conftest import requires_db
from io_assistant.backend.embed import EmbedError
from io_assistant.backend.backfill import backfill_embeddings
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.timezone.utc)


class Flaky:
    def __init__(self, up):
        self.up = up

    def embed(self, ts):
        if not self.up:
            raise EmbedError("down")
        return [[0.25] * 768 for _ in ts]

    def embed_one(self, t):
        return self.embed([t])[0]


def _seed(db):
    u = m.Utterance(text="s", source="text", captured_at=NOW)
    db.add(u)
    db.flush()
    db.add_all([
        m.Person(canonical_name="Nafay", aliases=[]),
        m.Place(name="Hunza", aliases=[]),
        m.Record(kind="note", title="gym", body="leg day", occurred_at=NOW,
                 attributes={}, source_utterance_id=u.id),
    ])
    db.flush()


@requires_db
def test_backfill_fills_null_embeddings(db):
    _seed(db)
    n = backfill_embeddings(db, Flaky(up=True))
    assert n == 3
    assert db.query(m.Person).one().embedding is not None
    assert db.query(m.Record).one().embedding is not None
    assert backfill_embeddings(db, Flaky(up=True)) == 0   # idempotent


@requires_db
def test_backfill_stops_quietly_when_embedder_down(db):
    _seed(db)
    assert backfill_embeddings(db, Flaky(up=False)) == 0
    assert db.query(m.Person).one().embedding is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `IO_TEST_DATABASE_URL=… uv run pytest tests/test_backfill.py -q -p no:warnings`
Expected: FAIL — `No module named 'io_assistant.backend.backfill'`.

- [ ] **Step 3: Implement** — create `io_assistant/backend/backfill.py`:

```python
"""Fill NULL embeddings once an embedder becomes available. Rows are written
without a vector when no embedder works (see embed_or_none); rows arriving from
another device (memory sync) also have none."""
from __future__ import annotations

import threading

from sqlalchemy import select

from io_assistant.backend.embed import EmbedError
from io_assistant.db import models as m

# (model, text-of-row) — same text the writers embed
_TARGETS = (
    (m.Person, lambda r: r.canonical_name),
    (m.Place, lambda r: r.name),
    (m.Item, lambda r: r.name),
    (m.Occasion, lambda r: r.name),
    (m.Record, lambda r: (r.title + "\n" + (r.body or "")).strip()),
)


def backfill_embeddings(session, embedder, *, batch: int = 32) -> int:
    filled = 0
    for model, text_of in _TARGETS:
        while True:
            rows = session.execute(
                select(model).where(model.embedding.is_(None)).limit(batch)
            ).scalars().all()
            if not rows:
                break
            try:
                vecs = embedder.embed([text_of(r) for r in rows])
            except EmbedError:
                return filled
            for r, v in zip(rows, vecs):
                r.embedding = v
            session.flush()
            filled += len(rows)
    return filled


class EmbeddingBackfiller:
    """Daemon thread, modelled on TrackerPoller: best-effort, never raises."""

    def __init__(self, session_factory, embedder, *, tick_s: float = 300.0):
        self._sf = session_factory
        self._embedder = embedder
        self._tick = tick_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def run_once(self) -> int:
        try:
            session = self._sf()
            try:
                n = backfill_embeddings(session, self._embedder)
                session.commit()
                return n
            finally:
                session.close()
        except Exception:  # pragma: no cover — worker must not die
            return 0

    def _run(self) -> None:
        if self._stop.wait(10.0):   # let startup finish first
            return
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(self._tick)
```

- [ ] **Step 4: Wire into the service** — in `io_assistant/service/app.py`, after the `if config.web.enabled:` poller block (before `app.state.index_queue = None`), add:

```python
    from io_assistant.backend.backfill import EmbeddingBackfiller

    backfiller = EmbeddingBackfiller(factory, orchestrator._embedder)
    backfiller.start()
    app.state.backfiller = backfiller

    @app.on_event("shutdown")
    def _stop_backfiller():
        backfiller.stop()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `IO_TEST_DATABASE_URL=… uv run pytest tests/test_backfill.py tests/test_service_health.py -q -p no:warnings`
Expected: all pass (the service still starts).

- [ ] **Step 6: Commit**

```bash
git add io_assistant/backend/backfill.py io_assistant/service/app.py tests/test_backfill.py
git commit -m "feat(embed): background backfill of NULL embeddings"
```

---

### Task 5: Startup, doctor and rules — Ollama optional end to end

**Files:**
- Modify: `dev.ps1` (add `Get-BackendSetting`; guard `Ensure-Ollama` call ~line 135)
- Modify: `scripts/setup.ps1` (steps 2/5)
- Modify: `io_assistant/doctor.py` (`_check_embeddings`, lines 76-83)
- Modify: `io_assistant/cli.py` (`doctor`, lines 148-154)
- Modify: `.claude/rules/local-first.md`, `.claude/knowledge/model-backends.md`, `.claude/skills/run-local.md`
- Test: `tests/test_doctor.py` (append)

**Interfaces:**
- Consumes: `BackendConfig.embedder/provider/builtin_embed_model/models_dir` (Task 1); `BuiltinEmbedder` (Task 2).
- Produces: `doctor._check_embeddings(config) -> Check`; CLI `io doctor --fetch-embedder`; PowerShell `Get-BackendSetting($key) -> string`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_doctor.py`:

```python
def test_embeddings_check_uses_builtin_when_ollama_down(config, monkeypatch):
    import io_assistant.doctor as d
    monkeypatch.setattr(d, "_ollama_tags",
                        lambda c: (_ for _ in ()).throw(OSError("refused")))
    monkeypatch.setattr(d, "_builtin_ready", lambda c: (True, "cached"))
    c = d._check_embeddings(config)
    assert c.ok and "built-in" in c.detail


def test_embeddings_check_fails_when_nothing_available(config, monkeypatch):
    import io_assistant.doctor as d
    monkeypatch.setattr(d, "_ollama_tags",
                        lambda c: (_ for _ in ()).throw(OSError("refused")))
    monkeypatch.setattr(d, "_builtin_ready", lambda c: (False, "fastembed not installed"))
    c = d._check_embeddings(config)
    assert not c.ok and "fastembed" in c.detail


def test_embeddings_check_ollama_mode_unchanged(config, monkeypatch):
    import io_assistant.doctor as d
    config.backend.embedder = "ollama"
    monkeypatch.setattr(d, "_ollama_tags", lambda c: ["nomic-embed-text:latest"])
    c = d._check_embeddings(config)
    assert c.ok and "nomic-embed-text" in c.detail


def test_doctor_fetch_embedder_flag(monkeypatch):
    from typer.testing import CliRunner
    import io_assistant.cli as cli
    import io_assistant.doctor as d
    fetched = []
    monkeypatch.setattr(d, "fetch_embedder", lambda c: fetched.append(1) or "ready")
    monkeypatch.setattr(d, "run_checks", lambda c: [d.Check("x", True, "ok")])
    monkeypatch.setattr(cli, "load_config", lambda: object())
    r = CliRunner().invoke(cli.app, ["doctor", "--fetch-embedder"])
    assert r.exit_code == 0 and fetched == [1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_doctor.py -q -p no:warnings`
Expected: 4 new FAIL (`no attribute '_builtin_ready'` / no `--fetch-embedder` option).

- [ ] **Step 3: Doctor** — in `io_assistant/doctor.py` replace `_check_embeddings` (lines 76-83) with:

```python
def _builtin_ready(config: Config) -> tuple[bool, str]:
    """(usable, detail) for the in-process embedder without loading the model."""
    if importlib.util.find_spec("fastembed") is None:
        return False, "fastembed not installed"
    cache = Path(os.path.expanduser(config.backend.models_dir))
    cached = cache.is_dir() and any(cache.iterdir())
    return True, "model cached" if cached else (
        "model downloads on first use (~520 MB); run `io doctor --fetch-embedder`")


def fetch_embedder(config: Config) -> str:
    """Download/load the built-in model now; returns a status line."""
    from io_assistant.backend.embed_builtin import BuiltinEmbedder

    BuiltinEmbedder(config).embed(["warm up"])
    return "built-in embedder ready"


def _check_embeddings(config: Config) -> Check:
    mode = config.backend.embedder
    want = config.backend.embed_model
    if mode != "builtin":
        try:
            tags = _ollama_tags(config)
            if any(t.startswith(want) for t in tags):
                return Check("embeddings", True, f"ollama: {want} present")
            ollama_note = f"ollama up but {want} not pulled"
        except Exception as e:  # noqa: BLE001
            ollama_note = f"Ollama unreachable ({str(e)[:40]})"
        if mode == "ollama":
            return Check("embeddings", False, ollama_note)
    else:
        ollama_note = "ollama not used"
    ok, detail = _builtin_ready(config)
    return Check("embeddings", ok, f"built-in: {detail} ({ollama_note})")
```

Ensure `from pathlib import Path` and `import os` are imported at the top of `doctor.py` (add if missing).

- [ ] **Step 4: CLI** — in `io_assistant/cli.py` replace the `doctor` command with:

```python
@app.command()
def doctor(
    fetch_embedder: bool = typer.Option(
        False, "--fetch-embedder",
        help="Download the built-in embedder model now (no Ollama needed)."),
) -> None:
    """Check the local stack (Postgres, pgvector, models, Whisper, Piper)."""
    from io_assistant import doctor as d

    config = load_config()
    if fetch_embedder:
        print(d.fetch_embedder(config))
    checks = d.run_checks(config)
    print(d.format_report(checks))
    raise typer.Exit(0 if all(c.ok for c in checks) else 1)
```

(`test_doctor_cli_exit_code` monkeypatches `d.run_checks` on the module, which this form still honours.)

- [ ] **Step 5: Run doctor tests**

Run: `uv run pytest tests/test_doctor.py -q -p no:warnings` → all pass.

- [ ] **Step 6: dev.ps1** — add above `Do-Up` (near `Test-WebEnabled`):

```powershell
function Get-BackendSetting($key, $default) {
  # crude TOML peek: uncommented `key = "value"` inside [backend]
  $cfg = Join-Path $Root "config.toml"
  if (-not (Test-Path $cfg)) { return $default }
  $inB = $false
  foreach ($line in Get-Content $cfg) {
    $t = $line.Trim()
    if ($t -match '^\[backend\]') { $inB = $true; continue }
    if ($t -match '^\[') { $inB = $false; continue }
    if ($inB -and $t -match ('^' + $key + '\s*=\s*"([^"]*)"')) { return $Matches[1] }
  }
  return $default
}

function Test-NeedsOllama {
  # Ollama is only needed for the local/hybrid chat model or as the embedder
  $provider = Get-BackendSetting "provider" "local"
  $embedder = Get-BackendSetting "embedder" "auto"
  if ($provider -ne "anthropic") { return $true }
  return ($embedder -eq "ollama")
}
```

Replace the bare `Ensure-Ollama` call in `Do-Up` with:

```powershell
  if (Test-NeedsOllama) { Ensure-Ollama }
  else { Ok "Ollama not needed (provider=anthropic, built-in embedder)" }
```

In `scripts/setup.ps1`, change step 2 to only pull when `config.toml` has `provider = "local"|"hybrid"` or `embedder = "ollama"`; otherwise print `2/5  Skipping Ollama (Anthropic provider + built-in embedder).` and, if `uv run io doctor --fetch-embedder` is desired, run it after step 4:

```powershell
$cfg = Get-Content config.toml -Raw
$needsOllama = ($cfg -notmatch 'provider\s*=\s*"anthropic"') -or ($cfg -match 'embedder\s*=\s*"ollama"')
if ($needsOllama) {
    Write-Host "2/5  Pulling Ollama models..."
    ollama pull llama3.2:3b
    ollama pull nomic-embed-text
} else {
    Write-Host "2/5  Skipping Ollama (Anthropic provider + built-in embedder)."
}
```
and add after step 5: `if (-not $needsOllama) { uv run io doctor --fetch-embedder }`.

Verify by hand: with `provider = "anthropic"` and Ollama stopped, `.\dev.ps1 up -NoWindow` prints "Ollama not needed" and no Ollama warning; `uv run io doctor` shows `embeddings  OK  built-in: …`. Flip `provider = "local"` → the old Ollama behaviour returns.

- [ ] **Step 7: Docs/rules** — `.claude/rules/local-first.md`: append sanctioned case 6:

```markdown
6. **HuggingFace model download** — only when `backend.embedder` is `"builtin"`
   (or `"auto"` and Ollama is unreachable) AND the fastembed model is not yet in
   `backend.models_dir`. A one-time GET of `nomic-ai/nomic-embed-text-v1.5`
   (~520 MB); nothing about the user is sent. After it is cached, embedding is
   fully offline. `io doctor --fetch-embedder` triggers it deliberately.
```
`.claude/knowledge/model-backends.md`: add a short "Embedder chain" section (auto → Ollama → fastembed → lexical + backfill; `embed_or_none`; files index needs an embedder). `.claude/skills/run-local.md`: note Ollama is optional with `provider = "anthropic"`.

Also fix the two `tests/test_orchestrator_files.py` tests that need a live Ollama: find where they build the real `Embedder` and give them `stub_embedder` (`grep -n "Embedder\|ollama" tests/test_orchestrator_files.py`); rerun them with Ollama stopped.

- [ ] **Step 8: Full verification**

Run: `IO_TEST_DATABASE_URL=… uv run pytest -q -p no:warnings --deselect tests/test_service_standby.py::test_standby_panel` with **Ollama stopped**.
Expected: all pass (previously 501 pass / 11 skip plus the new tests). Then run `.\dev.ps1 up -NoWindow` with `provider = "anthropic"` and Ollama stopped and issue one store + one query through `POST /utterance` (needs `ANTHROPIC_API_KEY`); expect both to succeed and `io doctor` to report the built-in embedder.

- [ ] **Step 9: Update state and commit**

Update `.claude/state/session.md` (A done) and move the item from `backlog.md` to `completed.md` (dated 2026-09-21).

```bash
git add dev.ps1 scripts/setup.ps1 io_assistant/doctor.py io_assistant/cli.py tests .claude
git commit -m "feat(setup): Ollama optional with provider=anthropic; doctor reports embedder"
```

---

## Self-review

- **Spec coverage:** embedder chain (Task 1), built-in model + packaging + size correction (Task 2), lexical safety net (Task 3), backfill (Task 4), startup/setup/doctor/rules (Task 5), tests for each spec testing bullet (cosine agreement and dim → Task 2 opt-in; lexical fallback on real Postgres → Task 3; backfill → Task 4; orchestrator-files tests → Task 5 step 7). Risk "first-use download offline" → covered by lexical fallback plus builtin-down memo.
- **Placeholders:** none; every code step carries code. The one grep-dependent step (`_VOICE_HIDDEN` join site in `io.spec`, and the orchestrator-files embedder construction) names the exact grep to run.
- **Type consistency:** `embed_or_none`, `OllamaUnavailable`, `BuiltinEmbedder.embed`, `backfill_embeddings(session, embedder, *, batch)`, `EmbeddingBackfiller.run_once`, `_builtin_ready`, `fetch_embedder` are used with identical names/signatures across tasks.
