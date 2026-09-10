# Model backends

**The `Backend` interface** — one Protocol, all model use behind it:

```
class Backend(Protocol):
    def route(self, utterance: str) -> Intent: ...
    def extract(self, utterance: str, now: datetime) -> ExtractionResult: ...
    def plan(self, question: str, now: datetime) -> QueryPlan: ...
    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str: ...
    def decide(self, utterance, now, *, context, files_enabled) -> Plan: ...  # optional
```

**`decide` — the unified planner** (`io_assistant/decide/`, spec
`2026-09-09-unified-decide-pipeline-design.md`). One call that returns a
`Plan` = ordered `Step`s (`store` w/ inline extraction | `query` | `file` |
`action` slug | `unknown`), so a turn can be multi-intent
("remind me X and what's on Friday" → a store step + a query step, merged into
one reply by `Orchestrator._merge_results`; a gate on any step pauses the turn).
`DecidePlanner` picks the mode from `[backend].decide` (`auto` default →
**combined** on anthropic/hybrid + local `quality`, **split** — the tuned
route+extract — on local `light`). Any parse/backend failure falls back to
split, so a bad response never breaks a turn. `AnthropicBackend.decide` is
implemented; `LocalBackend` has no `decide` (always split).
`io_assistant/actions/registry.py` lists the `action` slugs
(`open_folder`/`show_photos`/`search_files`) + their arg schemas; the
orchestrator validates the slug/args before dispatching to a whitelisted
handler. Grounding/persist/SQL stay deterministic — `decide` is route+extract+
plan folded together, nothing more (LLM boundary intact).

- **LocalBackend** — talks to Ollama. Default. Enforces the resource budget
  (on-demand load, short `keep_alive`, one model at a time, capped threads).
- **AnthropicBackend** — uses the `anthropic` SDK. Default model
  `claude-haiku-4-5` ($1 / $5 per 1M tokens); `claude-sonnet-5` available for
  more extraction quality. The user provides their own credential; IO never
  creates or manages it.
- **HybridBackend** — cheap high-frequency `route` goes local; quality-sensitive
  `extract` / `plan` / `phrase` go to Anthropic.

Selected in `config.toml`:

```toml
[backend]
provider = "local"          # "local" | "anthropic" | "hybrid"
profile  = "light"          # "light" | "quality"  (local/hybrid only)
anthropic_model = "claude-haiku-4-5"
```

**Embeddings are always local** (`embed()` → Ollama `nomic-embed-text`),
regardless of `backend.provider`, so the pgvector space stays stable — switching
provider never requires a re-embed. Changing the embedding model is an Alembic
migration + backfill.

**Why the swap is safe** — the LLM boundary (see `architecture.md`): the model
only routes/extracts/plans/phrases; all SQL, dates, filtering and ranking are
deterministic. A weaker model extracts less well but cannot corrupt the
datastore.

**When to switch** — poor extraction quality on `light` for the user's phrasing
→ try `quality`, then `hybrid`, then `anthropic`. Machine too GPU-loaded by
other work → `anthropic` (only Whisper stays local; STT can be disabled to go
fully thin). Absolute offline requirement → stay `local`, accept the quality
ceiling.

**Prompting small local models (learned 2026-09-07, llama3.2:3b)** — a 3B model
in Ollama `format: json` mode is brittle about prompt shape:
- Do NOT put `ExtractionResult.model_json_schema()` in the prompt — the verbose
  `$defs` dump makes it echo the schema back and extract nothing. Use the
  compact hand-written `SCHEMA_JSON` hint in `io_assistant/extract/schema.py`.
- Do NOT format few-shot examples as fenced ```json blocks — it parrots every
  example verbatim. Use plain `INPUT: …\nOUTPUT: {compact json}` pairs
  (`_EXAMPLES` in `schema.py`).
- Keep an explicit "describe only this sentence, never copy an example" line in
  both `prompts/extract.txt` and `local.py`'s extract system prompt.
- Real-world accuracy on the fixture set is ~80–90% run-to-run, so
  `tests/test_extractor.py::test_extractor_against_fixtures` asserts a pass
  **rate** (≥ 0.75), not every case. If that drops, the light profile has
  regressed — bump to `quality`/`hybrid`.
Claude (the `anthropic` backend) handles either prompt shape fine.
