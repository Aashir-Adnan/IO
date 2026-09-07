# Backlog (highest priority on top)

- Extraction eval quality: `tests/fixtures/utterances_store.json` cases 1-3 & 6
  overlap the few-shot `_EXAMPLES` in `extract/schema.py`, so
  `test_extractor_against_fixtures` partly measures shot reproduction. Add
  several genuinely held-out utterances (varied phrasing, multi-record, negation)
  and re-baseline the pass-rate threshold.
- Deferred minors from Plan 1 review (see ledger): unused `field_validator`
  import in config.py; `aliases` columns NOT NULL without server_default;
  redundant PK-leading-column indexes on link tables; malformed-Ollama-JSON
  (KeyError) not wrapped in LocalBackendError; `EntityResolver.resolve()` ignores
  the caller-supplied `aliases` arg for matching and fuzzy step skips stored
  aliases; `persist_store` resolves `assigned_by` / record-referenced entity
  names only when they also appear in the top-level people/places/items lists
  (silently dropped otherwise); unparseable `recurrence_phrase` persists
  silently (not gated); `persist_store` `items` link path has no test.
- Date grounding vs 3B model: `ground()` returns ok=False for absolute/ISO dates,
  and llama3.2:3b sometimes emits an ISO datetime as `when_phrase` (despite the
  prompt saying "copy the raw phrase") → every such record needlessly gates.
  Fix: (a) `ground()` should parse ISO-8601 and common absolute date strings via
  `dateutil.parser` and return ok=True; (b) tighten the extract prompt /
  post-process to strip model-invented ISO timestamps back toward "today".
- CLI hardening (Plan 3/4 or standalone): `io repl` should catch per-line
  exceptions and continue instead of dying; persist `stripped` not raw `line`
  into `Utterance.text` (cli.py); rename `_make_session_factory` (returns a
  tuple); optionally cache the Orchestrator across repl lines.
- Router quality on light profile: llama3.2:3b intent classification runs ~78%
  on the 9-item `utterances_route.json` fixture (opt-in test threshold lowered
  0.8→0.7). Improve `prompts/route.txt` (few-shot examples, tighter definitions),
  grow the fixture, and/or route on `quality`/cloud even in hybrid. This matters
  for hybrid users (routing stays local).
- Spec §4.5: `persist_store`/resolver never merge an extraction's `aliases` /
  new `notes` into an already-matched entity row (aliases are write-once at
  creation). Implement alias/notes enrichment on resolve-hit.
- `Config` should validate `embedding_dim == db.models.EMBED_DIM` (they can
  silently diverge; a mismatch fails opaquely at pgvector insert).
- Gate UX (spec §4.3): replying "no" to a confirmation gate currently gets
  routed+stored as a fresh utterance; gate message should also carry a one-line
  "about to store: …" summary (the `_summarize` builder already exists).
- `Orchestrator.handle` calls `session_factory()` and never closes the session —
  a connection leak for any real `sessionmaker` (matters for Plan 3 FastAPI).
- `EntityResolver.resolve` full-scans the entity table and fuzzy-scores every row
  in Python per call — fine now, revisit before Plan 2 query load.
- Occasion dedupe is global by lowercased name (two people's "birthday" collapse;
  a later better `date_phrase` never updates the row).
- Add an integration test for `persist_store` that COMMITS and reopens a fresh
  session to prove the utterance row physically survives a `PersistError`
  (current tests use the rolled-back `db` fixture; the transaction semantics were
  verified by inspection in the Plan 1 final review but not by a committing test).
- Declare the b-tree/GIN/HNSW indexes on the ORM models (currently only in
  `0001_initial.py`) so `alembic check` / autogenerate is clean and can gate CI.
  Until then the migration is hand-maintained (conftest now builds the test
  schema via `alembic upgrade head`, so drift in columns/types/nullability is
  caught, but not indexes).
- Plan 2: query pipeline (planner, SQL compiler, hybrid retrieval, respond)
- Plan 3: FastAPI service + pywebview desktop app
- Plan 4: voice (faster-whisper, push-to-talk, passive mode, io doctor)
