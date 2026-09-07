# Architecture

IO is one local Python application, layered, each layer with a single
responsibility and a defined interface so it is testable in isolation. The
layers in pipeline order: **Capture** (hotkey, mic, VAD, typed input) →
**Transcribe** (`faster-whisper`, voice only) → **Route** (STORE / QUERY /
UNKNOWN) → for STORE: **Extract** → **Resolve** (entity resolution + confirmation
gate) → **Persist** (one transaction); for QUERY: **Plan** → **Retrieve**
(structured SQL + semantic) → **merge / rank / expand recurrences** → **Respond**
(phrase the answer). The **Orchestrator** wires the pipeline, owns config,
logging and session state, and exposes the FastAPI service. All input paths
converge as a common `Utterance` object
`{ text, source, captured_at, transcription_confidence }`.

Every model call goes through the `Backend` interface (see `model-backends.md`),
never a hardcoded Ollama client. Embeddings are always generated locally
regardless of backend so the vector space stays stable.

**The LLM boundary (hard rule):** the model is used only for intent routing,
structured extraction, query planning, and final answer phrasing. It never emits
SQL, never does date arithmetic, never filters or ranks. All logic, dedup, date
grounding, filtering, ranking, and SQL construction is deterministic application
code. This is what makes the local/cloud backend swap safe: a weaker model
extracts less well but cannot corrupt the datastore. Enforced by
`rules/llm-boundaries.md`.
