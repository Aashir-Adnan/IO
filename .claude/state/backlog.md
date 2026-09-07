# Backlog (highest priority on top)

- Extraction eval quality: `tests/fixtures/utterances_store.json` cases 1-3 & 6
  overlap the few-shot `_EXAMPLES` in `extract/schema.py`, so
  `test_extractor_against_fixtures` partly measures shot reproduction. Add
  several genuinely held-out utterances (varied phrasing, multi-record, negation)
  and re-baseline the pass-rate threshold.
- Deferred minors from Plan 1 review (see ledger): unused `field_validator`
  import in config.py; `aliases` columns NOT NULL without server_default;
  redundant PK-leading-column indexes on link tables; malformed-Ollama-JSON
  (KeyError) not wrapped in LocalBackendError.
- Plan 2: query pipeline (planner, SQL compiler, hybrid retrieval, respond)
- Plan 3: FastAPI service + pywebview desktop app
- Plan 4: voice (faster-whisper, push-to-talk, passive mode, io doctor)
