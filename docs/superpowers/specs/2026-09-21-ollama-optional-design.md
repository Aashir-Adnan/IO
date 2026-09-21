# Ollama-optional: run IO on an API key alone

Date: 2026-09-21 · Status: approved design, awaiting spec review

## Problem

`provider = "anthropic"` still needs Ollama: `Embedder`
(`io_assistant/backend/embed.py`) calls Ollama's `/api/embed` on every store,
entity resolve and semantic retrieve, and Anthropic has no embeddings API. With
Ollama off, those calls raise `EmbedError`. `scripts/setup.ps1` hard-requires
Ollama and `dev.ps1`'s `Ensure-Ollama` starts it unconditionally.

## Goal

IO runs completely on Ollama (`provider = "local"`, unchanged) **or** completely
on an Anthropic API key with no Ollama installed. Out of scope: an OpenAI
provider (decided against for now).

## Design

1. **Embedder chain.** New `[backend] embedder = "auto" | "ollama" | "builtin"`,
   default `auto`. `Embedder` (the only class that changes) tries Ollama first
   (a connection failure marks it down and it is not retried for 60 s),
   otherwise a built-in in-process embedder: `fastembed` (ONNX) running
   `nomic-ai/nomic-embed-text-v1.5`. That is the same model and 768 dimensions as
   Ollama's `nomic-embed-text`, so **no migration and no backfill**; existing
   vectors stay valid. Text is embedded raw (no task prefix) on both paths, as
   Ollama does today. Model files cache under `~/.local/share/io/models`. `builtin_embed_model` may be set to `nomic-ai/nomic-embed-text-v1.5-Q` (~130 MB) to trade fidelity for size.
2. **Lexical safety net.** If neither embedder works, `EmbedError` is caught at
   the vector call sites (`resolve/resolver.py` lookups, `query/retrieve.py`
   semantic branch). They fall back to the existing fuzzy + `pg_trgm` matching.
   Writes store `embedding = NULL` (columns are nullable except `file_chunks`,
   whose indexing is deferred until an embedder is available).
3. **Backfill.** A startup daemon thread re-embeds `embedding IS NULL` rows in
   small batches once an embedder is available. This also serves memory sync
   (rows arriving from another device have no local vector).
4. **Startup / onboarding.** `dev.ps1` `Ensure-Ollama` and `setup.ps1`'s
   `ollama pull` run only when `provider != "anthropic"` and
   `embedder != "builtin"`. `setup.ps1` gains an optional model pre-fetch step
   (`io doctor --fetch-embedder`). `io doctor`'s `embeddings` check reports the
   active embedder and whether a fallback is in use.
5. **Rules.** `local-first.md` gains one sanctioned outbound case: the one-time
   model download from HuggingFace, only when the built-in embedder is selected
   and the model is not yet cached. `resource-budget.md`: the built-in embedder
   loads lazily and is capped to `num_thread`.
6. **Packaging.** `fastembed` added to `pyproject.toml`; `packaging/io.spec`
   hidden imports updated (onnxruntime is already bundled for Piper).

## Testing

- Cosine similarity between Ollama and built-in vectors for the same text
  > 0.98 (opt-in, needs both; well above the 0.85 vector-match threshold).
- Built-in embedder returns correct dim/length (opt-in, needs the model).
- Lexical fallback: resolver and retrieve work against real Postgres with a
  `FakeEmbedder` that raises `EmbedError`; rows store with NULL embedding; the
  backfill fills them when the embedder recovers. No DB mocks.
- `test_orchestrator_files.py` tests that need a live Ollama switch to the
  fake embedder.

## Risks

- ONNX vs Ollama's GGUF quantisation gives near-identical, not bit-identical,
  vectors; the cosine test guards it.
- First-use model download (~520 MB (fp32)) needs network once; the fallback covers
  the offline first run.
