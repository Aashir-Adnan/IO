# Local stack

**Services** (the user installs these; `run-local.md` has exact commands, and
`io doctor` will check them in Plan 4):

- **PostgreSQL 16 + pgvector** — run locally via Docker Compose
  (`pgvector/pgvector:pg16`), databases `io` and `io_test`, user/password
  `io`/`io`, port 5432. `CREATE EXTENSION vector;` in both databases.
- **Ollama** — the local model service and the default backend. `light` profile
  pulls `llama3.2:3b` (instruct) and `nomic-embed-text` (embeddings, always
  local ~140M params). `quality` profile uses a 7–8B Q4 instruct model
  (e.g. `qwen2.5:7b`).
- **faster-whisper** — local STT, CUDA. `base` model on `light`, `small` on
  `quality`. Plan 4.

**Target hardware** — ASUS TUF Dash F15: Intel i7 11th gen, 24 GB RAM, RTX 3060
Laptop (6 GB VRAM), Windows 11. All model choices assume this envelope. Idle
resident VRAM is ~0 (models unload); mid-request is ~3–4 GB on `light`, ~5.5 GB
on `quality`. On `light` a single call briefly uses roughly half the GPU and a
few CPU threads then releases — the machine stays usable. See
`rules/resource-budget.md`.

**Config** — a single `config.toml`: `[backend]` (provider + profile),
thresholds, hotkey, passive on/off, database URL, embedding dimension, top-N.
Plus `.env` for the database URL and (only if the cloud backend is used) the
Anthropic credential — never written to `config.toml`.
