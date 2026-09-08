# File index & text exploration (Phase 2A, 2026-09-08)

Opt-in subsystem (`[files].enabled`) that lets IO read files under user-approved
locations and answer from them, with a persistent graph-shaped index so repeat
searches cost almost no model tokens. **Not life-memory** — separate tables,
separate package. Spec: `docs/superpowers/specs/2026-09-08-io-phase-2-file-index-design.md`.

## Tables (migration `0004`)

- **`file_nodes`** — one row per file or dir. `path_key` (dedup: lower-cased on
  Windows) is the unique key. `content_hash` vs `index_hash` is the staleness
  gate — a node is stale iff `status='pending'` OR the two differ.
  `registered_root=true` marks a user registration entry point (`io files list`
  shows these; `forget` deletes the subtree). `summary` + `embedding` (of the
  summary) for text files; `caption` / `media_kind` / `thumb_path` reserved for
  Spec C.
- **`file_chunks`** — chunked text (~400 tok), `embedding` + a generated `tsv`
  (`to_tsvector('english', text)`) for FTS.
- **`file_edges`** — `contains` (dir→child) and `references` (one file's text
  names another node's basename). *shares-entity* is derived at query time by
  self-joining `file_entity_links`, never stored.
- **`file_entity_links`** — polymorphic `(file_id, etype, entity_id)` into
  people/places/items/occasions. Written **only when a name already resolves**
  (`resolve_query_entities`) — Phase 2A never creates entities from a model
  summary. Entity creation from user captions is Spec C.

## `io_assistant/files/` modules

| module | role |
|---|---|
| `paths.py` | `AccessGate` — the **only** thing that authorizes a read. Deny by default: allowed iff under a registered path/ancestor or an `allowlist_root`, not matched by `exclude_globs`, not a symlink (unless `follow_symlinks`). |
| `walk.py` | `walk_dir` — bounded discovery; prunes excluded dirs, caps at `max_files_per_registration`. |
| `extract.py` | `read_document` — text by type (txt/md/pdf via pypdf/docx via python-docx/html/rtf/csv); NUL-byte + printable-ratio binary guard. |
| `chunk.py` | `chunk_text` — paragraph-aware, overlap, hard-split, cap. Pure. |
| `store.py` | `FileIndex` — register / `stale()` / `neighbors()` / `link_entity` / `add_edge` / `forget` (Python-side prefix match: Windows `\` breaks SQL LIKE) / `status_summary`. |
| `index.py` | `FileIndexer.index_path` — **hash-gated**: unchanged `content_hash` ⇒ return, no read/embed/model call. Otherwise read → chunk → embed (local, always) → `summarize_file` → resolve names → link entities → reference/contains edges. |
| `command.py` | `classify_file_command` (register verb + path/phrase regex → register, else search) and `resolve_register_target` (rapidfuzz over registered dirs + allowlist children → one/many/none). |
| `search.py` | `FileSearcher.search` — deterministic discovery (FTS + pgvector KNN on chunks & node summaries + entity links + one-hop graph) → `rank()` (recency·0.30 + similarity·0.30 + lexical·0.20 + entity·0.15 + neighbor·0.05) → **freshness pass** (stat the top N, re-index changed ones now) → `answer_from_files`. Empty ⇒ deterministic "nothing" with no model call. |
| `cards.py` | `files_card(FileAnswer) -> FilesCard`. |
| `queue.py` | `IndexQueue` — the service's single background index thread (concurrency 1). CLI indexes synchronously. |

## LLM boundary

Discovery, ranking, freshness, entity identity, and edge construction are
deterministic Python. The model is called for exactly three things, all
mirroring existing uses:
- routing → the coarse `file` intent (`Intent`, `route.txt` FILE class);
- `Backend.summarize_file(title, head_text)` → `{summary, names, references}`,
  every part deterministically validated before use;
- `Backend.answer_from_files(question, files, shape)` → phrases strictly from
  supplied summaries + ≤3 excerpts per file.

## Cloud boundary

When `backend.provider != "local"`, `summarize_file` / `answer_from_files` send
file text to `api.anthropic.com` (user-approved). **Embeddings are always
local.** `io files add` prints a one-time notice when the provider isn't local;
the `[files]` config comment says the same.

## Surfaces

- **Router turn:** `file` intent → `Orchestrator._file_turn` → register
  (`_file_register`, ambiguous ⇒ candidate list, no gate) or search
  (`FilesCard` in the turn, `intent_kind="files"`).
- **Service** (404 when disabled): `POST /files`, `GET /files`,
  `DELETE /files`, `POST /files/reindex`, `GET /files/status`,
  `GET /files/content?path=`. `app.state.index_queue`.
- **CLI:** `io files add|list|reindex|forget|search|status`.
- **Frontend:** a **Files** rail view (`frontend/views/files.js`) — registered
  roots, add path, per-root status, reindex/remove; the `files` card
  (`components/card.js`) lists hits, click → `GET /files/content` in a `<pre>`
  viewer.

## Deferred

Media gallery / thumbnails / video playback / per-item captioning →
**Spec C** (`…-io-phase-2-media-library-design.md`). Also: agentic exploration
loop, `query`↔`file` cross-fallback, filesystem watching, learned co-retrieval
edges, OCR for scanned PDFs (spec §13).
