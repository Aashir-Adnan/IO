# Model backends

**The `Backend` interface** — one Protocol, all model use behind it:

```
class Backend(Protocol):
    def route(self, utterance: str) -> Intent: ...
    def extract(self, utterance: str, now: datetime) -> ExtractionResult: ...
    def plan(self, question: str, now: datetime) -> QueryPlan: ...
    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str: ...
```

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
