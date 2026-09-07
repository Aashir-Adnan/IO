# IO — Phase 1 Design

**Date:** 2026-09-07
**Status:** Approved for implementation planning
**Phase:** 1 of N

---

## 1. Vision & scope

IO is a fully local, single-user AI assistant. It runs on the user's own machine
with no API keys, no subscriptions, and no cloud services. It listens or reads
what the user tells it, and over time builds a structured, queryable record of
the user's life — events, people, places, things, tasks — plus a verbatim log of
how the user talks and types (for later mannerism modelling).

### Target hardware

ASUS TUF Dash F15 — Intel i7 (11th gen), 24 GB RAM, RTX 3060 Laptop (6 GB VRAM),
Windows 11. All model choices assume this envelope.

### Phase 1 delivers

Local voice/text capture → intent routing → structured extraction & storage →
hybrid (structured + RAG) query answering, exposed through both a CLI and a
desktop chat app. Fully offline.

**In scope:**

- Push-to-talk (global hotkey) + typed-text input.
- Optional passive always-listening mode behind a config flag (off by default).
- Local speech-to-text via `faster-whisper`.
- Intent routing: `STORE`, `QUERY`, `UNKNOWN`. No `SEND`.
- LLM structured extraction → deterministic entity resolver → PostgreSQL.
- Hybrid query pipeline: planner → structured SQL + semantic retrieval → merge/rank
  → LLM phrasing.
- Confirmation step only on low extraction confidence or ambiguous entity
  resolution.
- Verbatim logging of every utterance (voice and text) with timestamps.
- Recurring items (chores) modelled as recurrence rules, expanded at query time.
- Desktop chat app (approach A: `pywebview` + local FastAPI backend), structured
  as a multi-view client with the chat view active and timeline/sources/review
  views stubbed.

**Explicitly deferred to later phases:**

- Sending messages of any kind (WhatsApp, email, SMS, calls).
- Ingesting external sources (email, WhatsApp, calendar).
- Active style-learning / the "attribute matrix" / personality modelling.
- Wake-word detection.
- Multi-user support.
- Any cloud or network fallback.

---

## 2. Architecture

A single local Python application, layered. Each layer has one responsibility,
communicates through a defined interface, and is testable in isolation.

| Layer | Responsibility | Key dependencies |
|---|---|---|
| **Capture** | global hotkey listener, mic capture, passive-mode VAD, typed input | `sounddevice`, `pynput` |
| **Transcribe** | audio → text | `faster-whisper` (CUDA) |
| **Route** | classify an utterance as `STORE` / `QUERY` / `UNKNOWN` | Ollama (small instruct model) |
| **Extract** | utterance → strict JSON matching the extraction schema | Ollama |
| **Resolve** | map extracted entities to existing DB rows (exact → fuzzy → vector → new); trigger the confirmation gate on ambiguity | `rapidfuzz`, `pgvector` |
| **Persist** | write normalized rows, link rows, embeddings, and the raw utterance in one transaction | SQLAlchemy |
| **Query** | planner → sub-queries → structured SQL + semantic retrieval → merge/rank → recurrence expansion | SQLAlchemy, `pgvector` |
| **Respond** | LLM phrases the final answer strictly from retrieved rows | Ollama |
| **Orchestrator** | wires the pipeline; owns config, logging, session state; exposes the FastAPI service | FastAPI |

### The LLM boundary (hard rule)

The local model is used **only** for: intent routing, structured extraction,
query planning, and final answer phrasing. It never emits SQL, never does date
arithmetic, never filters or ranks data. All logic, dedup, date grounding,
filtering, ranking, and SQL construction is deterministic application code.

### Data flow

```
                        ┌─────────────┐
 hotkey / mic / text ──▶│   Capture   │
                        └──────┬──────┘
                               ▼
                        ┌─────────────┐   (voice only)
                        │ Transcribe  │
                        └──────┬──────┘
                               ▼
                        ┌─────────────┐
                        │    Route    │──── UNKNOWN ──▶ log + ask user to rephrase
                        └──┬───────┬──┘
                    STORE  │       │  QUERY
                           ▼       ▼
                  ┌────────────┐  ┌────────────┐
                  │  Extract   │  │  Plan      │
                  └─────┬──────┘  └─────┬──────┘
                        ▼               ▼
                  ┌────────────┐  ┌──────────────────────┐
                  │  Resolve   │  │ Retrieve per subquery │
                  │ (+ gate)   │  │  structured SQL  +    │
                  └─────┬──────┘  │  semantic (pgvector)  │
                        ▼         └─────────┬────────────┘
                  ┌────────────┐            ▼
                  │  Persist   │   ┌──────────────────┐
                  └─────┬──────┘   │  merge / rank /  │
                        ▼          │  expand recur.   │
                  confirmation     └────────┬─────────┘
                  or silent ack             ▼
                                     ┌────────────┐
                                     │  Respond   │
                                     └─────┬──────┘
                                           ▼
                                   text / md / mermaid
```

All three input paths (hotkey, passive mic, typed) converge at the Orchestrator
as a common `Utterance` object: `{ text, source, captured_at, transcription_confidence }`.

---

## 3. Data model (PostgreSQL 16 + pgvector)

### Tables

- **`utterances`** — `id`, `text` (raw, verbatim), `source` (`voice` | `text`),
  `captured_at timestamptz`, `transcription_confidence float null`,
  `resolved_intent` (`store` | `query` | `unknown`). Never mutated after insert.
- **`people`** — `id`, `canonical_name`, `aliases text[]`, `notes`,
  `embedding vector`, `created_at`, `updated_at`.
- **`places`** — `id`, `name`, `type` (e.g. restaurant, home, office),
  `aliases text[]`, `embedding vector`, timestamps.
- **`items`** — `id`, `name`, `category` (food, object, media, …),
  `aliases text[]`, `embedding vector`, timestamps.
- **`events`** — `id`, `description`, `occurred_at timestamptz`,
  `attributes jsonb` (freeform extracted detail), `source_utterance_id fk`,
  `embedding vector`, `created_at`.
- **`tasks`** — `id`, `title`, `source` (`family` | `job` | `chore` | `self`),
  `assigned_by_person_id fk null`, `due_at timestamptz null`,
  `status` (`open` | `done` | `dropped`), `recurrence_rule text null` (iCal RRULE),
  `attributes jsonb`, `source_utterance_id fk`, `embedding vector`, timestamps.
- **`occasions`** — `id`, `name` (e.g. "Eelian's birthday"), `date`,
  `recurrence_rule text null`, `embedding vector`, timestamps.

### Link tables

`event_people`, `event_places`, `event_items`, `event_occasions`,
`occasion_people`. Each is `(event_id|occasion_id, entity_id, role text null)`.

### Indexing

- Every text-bearing row (`people`, `places`, `items`, `events`, `tasks`,
  `occasions`) has an `embedding vector` column with an **HNSW** index for
  approximate nearest-neighbour search.
- B-tree indexes on every foreign key and every timestamp column
  (`occurred_at`, `due_at`, `captured_at`, `date`).
- GIN index on `aliases` arrays.

### Migrations

Alembic from the first commit. Every schema change is a migration; no ad-hoc
`ALTER` statements, ever.

### Embeddings

Generated by Ollama (`nomic-embed-text` or equivalent) at write time, stored in
the row's `embedding` column. Dimension fixed in config; a model change is a
migration + backfill.

---

## 4. Extraction & storage pipeline

Runs when Route returns `STORE`.

### 4.1 Extract

- Prompt: system schema description + few-shot examples + the utterance.
- Output: JSON only — arrays of `people`, `places`, `items`, `occasions`, and one
  or more `events` and/or `tasks`. Each record carries only the fields the model
  can fill plus a `confidence` float in `[0, 1]`.
- Validation: parsed into Pydantic models. On failure, one retry with a
  "return valid JSON matching the schema" nudge. Second failure → route becomes
  `UNKNOWN`, utterance logged with an `extraction_failed` marker for later review.

### 4.2 Resolve entities

For each extracted person / place / item, in order:

1. **Exact** match on `canonical_name`/`name` or any alias (case-insensitive) → use it.
2. **Fuzzy** match (`rapidfuzz` token-set ratio) above the high threshold
   (config, default 92) → use it.
3. **Vector** similarity above the similarity threshold (config, default 0.85)
   → **ambiguous**: hold for the confirmation gate.
4. **No match** → stage a new entity for creation.

### 4.3 Confirmation gate

Triggered only by:

- an ambiguous vector-only resolve (step 3), or
- any extracted record with `confidence` below the gate threshold (config,
  default 0.6), or
- a date/time the grounder (4.4) could not resolve.

When triggered: the assistant emits a one-line summary of what it's about to
store and waits for `yes` / `no` / a correction. When not triggered: it stores
silently and then prints a summary of what it wrote.

### 4.4 Ground dates

Deterministic app code resolves relative time expressions ("last Tuesday", "this
morning", "for his birthday") against `now()` and, for occasion references,
against stored `occasions` rows. The model never computes dates.

### 4.5 Persist

One transaction:

1. Insert new entities; update existing entities' `aliases`/`notes` if the
   utterance adds detail.
2. Insert the `event`(s) / `task`(s).
3. Insert link rows.
4. Compute and store embeddings for every new/updated text row.
5. Stamp `source_utterance_id` everywhere; set `utterances.resolved_intent = 'store'`.

### 4.6 Recurring items

"I take the trash out every Monday" → a `task` with `recurrence_rule` set and
`due_at` null. Never expanded at store time.

---

## 5. Query pipeline (hybrid structured + RAG)

Runs when Route returns `QUERY`.

### 5.1 Plan

The model converts the question into a `QueryPlan`:

```
QueryPlan = {
  subqueries: [
    {
      target_type: "event" | "task" | "person" | "place" | "occasion",
      entities: [ "<name>", ... ],          # referenced entities, unresolved
      time_window: { start: <ISO|null>, end: <ISO|null> } | null,
      source_filter: [ "family", "job", "chore", "self" ] | null,
      status_filter: [ "open", "done", "dropped" ] | null,
      semantic_hint: "<short phrase to embed>" | null,
      aggregation: "list" | "count" | "latest" | null
    }, ...
  ],
  answer_shape: "text" | "markdown" | "diagram"
}
```

- "What work do I have today" → subqueries over `tasks`:
  one with `source_filter=["family","job"]`, `status_filter=["open"]`,
  `time_window` = today-or-overdue; plus recurring `chore` tasks whose RRULE
  fires today (handled in 5.4).
- A simple question ("where did I eat yesterday") produces a single subquery and
  skips planning overhead where possible.
- Time windows in the plan are grounded by app code, not the model.

### 5.2 Retrieve — both paths, every subquery

- **Structured:** the subquery filters compile to a single parameterized SQL
  statement (time window, resolved entity foreign keys, source, status). This is
  the authoritative spine of the result.
- **Semantic:** if `semantic_hint` is present, embed it and run a pgvector
  nearest-neighbour search **constrained to the same `target_type` and the same
  time window**. Never an unbounded scan.
- Union the two result sets; dedupe by row id. Tag each row with its provenance
  (`structured` / `semantic` / `both`).

### 5.3 Merge & rank

Combine all subquery results. Rank by a weighted blend of:

- recency (relative to the query's time window),
- vector similarity score (0 when structured-only),
- structured relevance (explicit due date / direct entity link > fuzzy match),
- provenance (`both` outranks either alone).

Cap at a configurable top-N (default 20) to bound the Respond model's context.

### 5.4 Expand recurrences

For any `task`/`occasion` with a `recurrence_rule` in the result window, expand
the RRULE to concrete instances within the window (using `dateutil.rrule`).

### 5.5 Phrase

The Respond model receives **only** the final ranked rows as JSON plus the
original question and `answer_shape`. It writes the natural-language answer,
instructed to:

- answer strictly from the provided rows,
- state explicitly when nothing matched,
- emit Markdown when `answer_shape = "markdown"`, a fenced `mermaid` block when
  `answer_shape = "diagram"`, plain text otherwise.

### 5.6 Efficiency properties

- Every retrieval is bounded by a type and (almost always) a time window.
- HNSW vector index + b-tree indexes keep both paths sub-linear.
- The planner runs once per question; top-N caps model context.
- History can grow to years of data without degrading query latency.

---

## 6. Capture & activation

- **Push-to-talk:** configurable global hotkey; press starts recording, release
  stops. Audio → Transcribe → pipeline.
- **Typed fallback:** the desktop app's input box and a CLI REPL both produce an
  `Utterance` with `source = "text"` and enter the pipeline at Route.
- **Passive mode (opt-in `config.toml` flag, default off):** continuous mic with
  local voice-activity detection; each speech segment is transcribed and routed.
  No wake-word engine in Phase 1 — passive mode routes everything it hears, so it
  is intended for deliberate hands-free sessions, not all-day listening.
- All paths converge at the Orchestrator as the common `Utterance` object.

---

## 7. Desktop app (approach A, structured for growth)

Phase 1 ships one active view (chat), but the app is built as a real multi-view
client so later phases add panels rather than requiring a rewrite.

### Backend

The Orchestrator runs as a local **FastAPI** service:

- REST endpoints for request/response (`POST /utterance`, `GET /health`, …).
- A **WebSocket** channel for streaming assistant output token-by-token and for
  pushing unprompted updates (needed once external-source ingestion lands in
  later phases).
- The CLI (`io run`) and the desktop app are both clients of this one service, so
  voice, typed, and GUI input share exactly one code path.

### Frontend

A structured HTML/JS app (not a single file) loaded in a `pywebview` window:

```
frontend/
  index.html
  app.js              # router, WebSocket client, shared state store
  views/
    chat/             # transcript, input box, send / hotkey status  [ACTIVE]
    timeline/         # chronological events & tasks                 [STUB]
    sources/          # connected external sources (email, WhatsApp) [STUB]
    review/           # "important stuff" queue awaiting keep/discard [STUB]
  components/
    message.js        # message bubble
    markdown.js       # Markdown renderer (bundled lib, no CDN)
    mermaid.js        # Mermaid diagram renderer (bundled lib, no CDN)
    entity-chip.js    # inline entity reference
  styles/
```

- **Rendering:** one `renderMessage()` handles all output — raw text passes
  through, Markdown renders, fenced ` ```mermaid ` blocks render as diagrams.
- **Offline constraint:** all JS/CSS libraries are vendored into the repo. No CDN
  references (would violate offline-only).
- **Phase 1:** `chat` is fully functional. `timeline`, `sources`, `review` are
  routed and visible in the nav but render a clear "coming in a later phase"
  placeholder — the shell is real so later phases only fill in views.

### How later phases plug in

Add an ingestion service behind the same FastAPI app → it pushes candidate items
over the existing WebSocket into the `review` queue → items the user keeps are
written through the **same** extract → resolve → persist pipeline built in
Phase 1.

---

## 8. Tech stack & project layout

- **Python 3.11+**, `uv` for environment and dependency management.
- **Ollama** as a local service. Models (names in `config.toml`):
  - small instruct model for route/extract/plan/phrase — e.g. `qwen2.5:7b` or
    `llama3.1:8b`, Q4 quantization, GPU offload.
  - `nomic-embed-text` for embeddings.
- **faster-whisper**, `small` or `medium` model, CUDA.
- **PostgreSQL 16** local + `pgvector` extension. **SQLAlchemy 2.x** + **Alembic**.
- **FastAPI** + `uvicorn` for the local service; **pywebview** for the window.
- **Config:** a single `config.toml` (model names, thresholds, hotkey, passive
  on/off, database URL, embedding dimension, top-N) plus `.env` for the database
  URL if the user prefers to keep it out of the toml.
- **Runs as:** a foreground process (`io run`) that starts the FastAPI service
  and opens the window. PostgreSQL and Ollama are the only background services.

### Repo layout

```
io/
  capture/           # hotkey, mic, VAD, typed input
  transcribe/        # faster-whisper wrapper
  route/             # intent classifier
  extract/           # schema, prompts, extractor
  resolve/           # entity resolution + confirmation gate
  persist/           # transactional writes, embedding generation
  query/             # planner, sql compiler, retrieval, ranking, recurrence
  respond/           # answer phrasing
  orchestrator.py    # pipeline wiring + FastAPI app
  db/
    models.py
    migrations/      # Alembic
  prompts/           # prompt templates, versioned
  config.py
frontend/            # see section 7
tests/
docs/superpowers/specs/
.claude/
  knowledge/  rules/  skills/  state/
CLAUDE.md
config.toml
pyproject.toml
```

---

## 9. Testing strategy

TDD throughout, per the Superpowers workflow — tests before implementation at
every stage.

- **Extraction:** a fixture set of utterances → expected JSON. Assert schema
  validity and field-level matches against the real local model, with tolerant
  matching on free-text fields.
- **Resolver:** pure unit tests. Seed entities, assert exact / fuzzy / vector /
  new outcomes and correct gate triggering. No model involved.
- **Query planner:** question → expected `QueryPlan` shape (fixtures).
- **SQL compilation:** `QueryPlan` subquery → expected parameterized SQL + params;
  execute against a disposable test PostgreSQL with seeded data and assert rows.
- **Ranking & recurrence:** deterministic unit tests over synthetic result sets.
- **End-to-end scenarios:**
  1. Store "I went out with Nafay to eat at Arcadian for his and Eelian's
     birthday" → assert an `event` with `occurred_at` today, linked people
     `Nafay` + `Eelian`, place `Arcadian`, occasion `birthday`.
  2. A week later, "Where have I hung out with Nafay in the past week" → the
     stored event is in the answer.
  3. Store three tasks from `family`, `job`, and `chore` sources → "What work do
     I have today" returns the right subset, including a chore whose RRULE fires
     today.
- **Test database:** a disposable local PostgreSQL (Docker or a dedicated local
  cluster); the DB is never mocked.
- **Offline check:** a test that fails if any component opens a non-local socket.

---

## 10. `.claude/` memory scaffold

Four project-local directories, wired into `CLAUDE.md`.

### `.claude/knowledge/`

- `architecture.md` — layer table, data flow, the LLM boundary.
- `data-model.md` — tables, links, indexing, embeddings, migration policy.
- `extraction.md` — schema, prompt design, resolver rules, gate triggers.
- `query-pipeline.md` — planner, hybrid retrieval, ranking, recurrence, efficiency.
- `local-stack.md` — Ollama / Whisper / Postgres setup, model names, hardware notes.
- `conventions.md` — code style, test layout, config approach.

### `.claude/rules/`

- `offline-only.md` — no API calls, no cloud, no telemetry, no CDN assets; any
  network dependency to a non-local host is a bug.
- `llm-boundaries.md` — the model never emits SQL, never does date math, never
  filters or ranks; deterministic code owns all logic.
- `test-discipline.md` — TDD, tests before implementation, real test Postgres,
  never mock the DB.
- `migrations.md` — every schema change is an Alembic migration.

### `.claude/skills/`

- `add-entity-type.md` — add a new extractable entity: schema, migration,
  resolver, prompts, tests.
- `add-query-capability.md` — support a new question shape: planner, SQL compiler,
  fixtures.
- `run-local.md` — bring up Postgres + Ollama + the app for manual testing.

### `.claude/state/`

- `backlog.md` — everything not yet done, highest priority on top.
- `completed.md` — finished tasks, dated, newest first.
- `session.md` — what is being worked on right now, plus which `knowledge/` files
  and `skills/` are in play for it.

### `CLAUDE.md`

References all four directories, states the offline-only prime directive, points
to `.claude/state/session.md` as the first file to read each session, and
enforces the `rules/` files.

---

## 11. Staged implementation outline

Each stage is independently testable and leaves the system in a working state.

1. **Scaffold** — repo layout, `pyproject.toml`/`uv`, `config.toml`, `.claude/`
   scaffold + `CLAUDE.md`, CI-less test runner. Test: config loads, package imports.
2. **Database foundation** — SQLAlchemy models, initial Alembic migration,
   pgvector setup, test-DB fixture. Test: migrate up/down, insert each entity.
3. **Persistence layer** — transactional writes + embedding generation (Ollama
   embed). Test: write the Arcadian event by hand, read it back with links.
4. **Resolver** — exact/fuzzy/vector/new + confirmation gate. Test: seeded-entity
   unit matrix.
5. **Extractor** — schema, prompts, Pydantic validation, retry. Test: fixture
   utterances → JSON.
6. **Router** — STORE/QUERY/UNKNOWN. Test: labelled fixture utterances.
7. **STORE path end-to-end** (text input only) — Route → Extract → Resolve →
   Persist. Test: scenario 1.
8. **Query planner** — question → `QueryPlan`. Test: fixtures.
9. **SQL compiler + retrieval** — structured path only. Test: plan → SQL → rows.
10. **Semantic retrieval + merge/rank + recurrence expansion**. Test: hybrid
    results, ranking, RRULE expansion.
11. **Respond** — phrasing with text/markdown/diagram shapes. Test: rows →
    answer, "nothing matched" case.
12. **QUERY path end-to-end** (text input). Test: scenarios 2 and 3.
13. **FastAPI service** — REST + WebSocket wrapping the Orchestrator. Test: HTTP
    client drives both scenarios.
14. **Desktop app shell** — `pywebview` window, router, chat view, vendored
    markdown + mermaid renderers, stub views. Test: manual + a headless DOM smoke
    test where feasible.
15. **Transcribe** — `faster-whisper` wrapper. Test: fixed WAV → expected text
    (tolerant).
16. **Capture** — push-to-talk hotkey + typed input wired to the service. Test:
    manual; unit-test the `Utterance` assembly.
17. **Passive mode** — VAD loop behind the config flag. Test: manual with a WAV
    stream; unit-test segmentation.
18. **Hardening** — offline-socket test, error surfaces in the UI, config
    validation, `run-local` skill verified.

---

## 12. Open questions / assumptions

- **Instruct model choice** (`qwen2.5:7b` vs `llama3.1:8b`) is settled empirically
  during stage 5–6 against the extraction fixtures; config-driven, so not
  blocking.
- **Whisper model size** (`small` vs `medium`) tuned in stage 15 against latency
  on the 3060.
- Assumes the user installs PostgreSQL + `pgvector` and Ollama themselves;
  `run-local.md` documents the exact steps and `io doctor` (stage 18) checks them.
