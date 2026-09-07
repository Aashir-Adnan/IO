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
- Plan 2: query pipeline (planner, SQL compiler, hybrid retrieval, respond)
- Plan 3: FastAPI service + pywebview desktop app
- Plan 4: voice (faster-whisper, push-to-talk, passive mode, io doctor)
