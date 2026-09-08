# IO Phase 2 · Spec A — File Index & Text Exploration

> Extends the Phase 1 / 1.5 specs. Phase 1.5 (conversational shell) is done.
> Phase 2 gives IO read access to files on the user's machine and a persistent,
> graph-shaped index of what it has seen, so repeat searches cost almost no
> tokens.
>
> Build order: **Spec A (this doc)** → Spec C (media library & captioning,
> `…-io-phase-2-media-library-design.md`). Spec B (desktop packaging) is
> independent.

## 1. Vision & scope

Today IO only knows what you have told it. This phase lets it also read the
documents you point it at — a lease, a batch of invoices, a folder of notes —
and answer from them: *"what does my lease say about pets?"*, *"find the invoice
from Granjur"*.

Two hard requirements shape the design:

1. **Cheap on repeat.** Every file is read and summarised **once**. The result
   (summary, chunk embeddings, extracted entities, edges) is stored. A later
   search is pure SQL + vector math over that store; the model is called only to
   phrase the final answer, and only ever sees short summaries plus a handful of
   text excerpts — never whole files, never the same file twice.
2. **The LLM boundary is untouched.** File *discovery, ranking and freshness*
   are deterministic Python. The model is used for exactly three things, all of
   which mirror existing uses (`route` / `extract` / `phrase`):
   - routing an utterance to the new coarse `file` intent,
   - `summarize_file` — a one-time summary + candidate entity names + referenced
     paths, every part of which is deterministically validated before use,
   - `answer_from_files` — phrasing an answer strictly from supplied material.

### In scope

- New tables `file_nodes`, `file_chunks`, `file_edges`, `file_entity_links`
  (migration `0004`).
- `io_assistant/files/` — an access gate, a directory walker, per-type text
  extraction, a chunker, a one-file indexer, a DB store with graph traversal,
  and a deterministic searcher.
- A new coarse router intent `file`, split by deterministic code into
  **register** vs **search**.
- `Backend.summarize_file` + `Backend.answer_from_files` (+ prompts, + all three
  backends, + `FakeBackend`).
- `Orchestrator` file branch; a new `FilesCard`; `intent_kind = "files"`.
- Service: `POST /files`, `GET /files`, `DELETE /files`, `POST /files/reindex`,
  `GET /files/status`, `GET /files/content`; a background index worker.
- CLI: `io files add|list|reindex|forget|search|status`.
- Frontend: a **Files** rail view (registered roots, add/remove/reindex, status)
  and a `files` card renderer with an in-app text viewer.

### Out of scope (later specs / backlog)

- Media gallery, thumbnails, video playback, captioning → **Spec C**.
- Agentic multi-step exploration (the read→decide→read loop) → backlog.
- Learned co-retrieval edges → backlog.
- Cross-fallback between life-memory `query` and `file` search in one turn →
  backlog (v1: the router picks one).
- Watching the filesystem for changes → backlog (v1: staleness is checked
  lazily, at search time, by content hash).

## 2. Global constraints

Copied verbatim from the project rules — every task inherits these:

- **local-first** (`.claude/rules/local-first.md`): no new outbound network
  traffic. The only sanctioned non-local call remains `api.anthropic.com` when
  `backend.provider` is `anthropic`/`hybrid`. `tests/test_e2e_store.py`'s socket
  guard must stay green.
- **File contents and the cloud:** the user chose *"allow cloud for files"* —
  when `backend.provider != "local"`, `summarize_file` and `answer_from_files`
  send file text to Anthropic like any other prompt context. This must be stated
  in the `[files]` config comment and printed once by `io files add` when the
  provider is not `local`. Embeddings are **always** generated locally
  (architecture rule), regardless of backend.
- **llm-boundaries** (`.claude/rules/llm-boundaries.md`): the model never emits
  SQL, never ranks, never decides which file answers. Discovery, ranking,
  freshness, entity identity, edge construction — deterministic Python.
- **migrations** (`.claude/rules/migrations.md`): schema changes are Alembic
  migrations only. `embedding_dim` stays `768` (`db.models.EMBED_DIM`).
- **resource-budget** (`.claude/rules/resource-budget.md`): the background index
  worker is single-threaded (concurrency 1), on-demand, and never runs during a
  model call. No background crawl of allowlist roots — they are touched only at
  search time.
- **test-discipline** (`.claude/rules/test-discipline.md`): TDD; never mock the
  database (real PostgreSQL at `IO_TEST_DATABASE_URL`); model calls may use
  `FakeBackend`.
- Package `io_assistant`; everything via `uv run`.

## 3. Data model — migration `0004_file_index`

All four tables get ORM models appended to `io_assistant/db/models.py` **with
their indexes declared in `__table_args__`** (so `alembic check` stays clean —
a standing backlog ask).

### 3.1 `file_nodes` — one row per file or directory

| column | type | notes |
|---|---|---|
| `id` | BigInteger PK | |
| `path` | Text NOT NULL | absolute, display form (`str(Path.resolve())`) |
| `path_key` | Text NOT NULL **UNIQUE** | dedup/lookup key: `path` lower-cased on Windows, `path` as-is on POSIX |
| `parent_key` | Text NULL | `path_key` of the containing directory; NULL for a filesystem root |
| `kind` | String(8) NOT NULL | `file` \| `dir` |
| `mime` | String(128) NULL | best-effort (`mimetypes.guess_type`) |
| `media_kind` | String(8) NULL | `image` \| `video` \| NULL — set by extension; **Spec C uses it**, Spec A only stores it |
| `size_bytes` | BigInteger NULL | |
| `content_hash` | String(64) NULL | sha256 hex of bytes; NULL for dirs and unread files |
| `mtime` | DateTime(tz) NULL | file mtime at last stat |
| `captured_at` | DateTime(tz) NULL | reserved for Spec C (EXIF); always NULL here |
| `registered_at` | DateTime(tz) NULL | set when the user registers this exact path |
| `registered_root` | Boolean NOT NULL, default `false` | true ⇒ a registration entry point (`io files list` shows these; `forget` deletes the subtree) |
| `indexed_at` | DateTime(tz) NULL | when summary/chunks were last built |
| `index_hash` | String(64) NULL | the `content_hash` the current index reflects |
| `title` | Text NULL | first heading / filename stem / model title |
| `summary` | Text NULL | model summary (text files), ≤ 400 chars |
| `caption` | Text NULL | reserved for Spec C (user-authored); always NULL here |
| `status` | String(16) NOT NULL, default `pending` | `pending` \| `ok` \| `too_large` \| `unreadable` \| `missing` \| `skipped` |
| `error` | Text NULL | short reason when `status` is a failure |
| `embedding` | Vector(768) NULL | embedding of `summary` (or `caption` in Spec C) |
| `created_at` / `updated_at` | DateTime(tz), server default `now()` | `updated_at` `onupdate=now()` |

Indexes: `UNIQUE(path_key)`; b-tree `parent_key`; b-tree `content_hash`; b-tree
`status`; b-tree `media_kind`; HNSW `embedding vector_cosine_ops`; partial
b-tree `registered_root WHERE registered_root`.

**Staleness rule:** a node is stale ⇔ `status = 'pending'` OR `index_hash IS
DISTINCT FROM content_hash`. `content_hash` is only refreshed by an actual stat
+ read, which happens lazily (search-time freshness pass, or an explicit
`reindex`).

### 3.2 `file_chunks` — chunked text for lexical + semantic search

| column | type | notes |
|---|---|---|
| `id` | BigInteger PK | |
| `file_id` | BigInteger FK `file_nodes` ON DELETE CASCADE, NOT NULL | |
| `ord` | Integer NOT NULL | 0-based |
| `text` | Text NOT NULL | one chunk (~`chunk_tokens`) |
| `token_estimate` | Integer NOT NULL | `len(text)//4` |
| `embedding` | Vector(768) NOT NULL | local embedding of `text` |
| `tsv` | tsvector, `GENERATED ALWAYS AS (to_tsvector('english', text)) STORED` | FTS |

Indexes: `UNIQUE(file_id, ord)`; HNSW `embedding vector_cosine_ops`; GIN `tsv`.

### 3.3 `file_edges` — the graph

| column | type | notes |
|---|---|---|
| `id` | BigInteger PK | |
| `src_id` / `dst_id` | BigInteger FK `file_nodes` CASCADE, NOT NULL | |
| `rel` | String(16) NOT NULL | `contains` (dir → direct child) \| `references` (src's text names dst's path or basename) |
| `detail` | Text NULL | for `references`: the matched string |
| `created_at` | DateTime(tz), server default `now()` | |

Indexes: `UNIQUE(src_id, dst_id, rel)`; b-tree `(src_id, rel)`; b-tree
`(dst_id, rel)`.

The third relationship from brainstorming, **shares-entity**, is *derived* at
query time by self-joining `file_entity_links` — no stored rows, no upkeep.

### 3.4 `file_entity_links` — files ↔ existing entities

| column | type | notes |
|---|---|---|
| `id` | BigInteger PK | |
| `file_id` | BigInteger FK `file_nodes` CASCADE, NOT NULL | |
| `etype` | String(8) NOT NULL | `person` \| `place` \| `item` \| `occasion` |
| `entity_id` | BigInteger NOT NULL | soft reference into `people`/`places`/`items`/`occasions` |
| `mentions` | Integer NOT NULL, default 1 | bumped on re-link |
| `source` | String(8) NOT NULL, default `summary` | `summary` (Spec A) \| `caption` (Spec C) |
| `created_at` | DateTime(tz), server default `now()` | |

Indexes: `UNIQUE(file_id, etype, entity_id)`; b-tree `(etype, entity_id)`.

Polymorphic rather than four `file_people`/… tables (unlike `record_*`): files
are not core life-memory and the only query is *"file ids for these entity
ids"*. The rows are written **only when a name already resolves** via
`EntityResolver.lookup` — Spec A never creates a `Person`/`Place`/… from a model
file summary (too noisy). Entity *creation* from files happens only from
user-authored captions, in Spec C, through the normal resolver + gate.

## 4. Config — `FilesConfig`

New model in `io_assistant/config.py`, `files: FilesConfig = FilesConfig()` on
`Config`, `[files]` block in `config.toml` (with `enabled = false` and the
cloud-boundary comment).

```python
class FilesConfig(BaseModel):
    enabled: bool = False
    allowlist_roots: list[str] = Field(default_factory=list)   # globbable pre-registration
    max_file_bytes: int = 2_000_000                            # bigger -> metadata only
    index_extensions: list[str] = Field(default_factory=lambda: [
        ".txt", ".md", ".markdown", ".rst", ".pdf", ".docx", ".rtf",
        ".csv", ".tsv", ".json", ".yaml", ".yml", ".html", ".htm", ".xml", ".log",
        ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rb", ".rs",
        ".c", ".h", ".cpp", ".sh",
    ])
    media_extensions: list[str] = Field(default_factory=lambda: [
        ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tiff",
        ".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi",
    ])
    exclude_globs: list[str] = Field(default_factory=lambda: [
        "**/.git/**", "**/node_modules/**", "**/__pycache__/**", "**/.venv/**",
        "**/.env*", "**/*.env", "**/*.pem", "**/*.key", "**/id_rsa*",
        "**/*.kdbx", "**/*.ppk", "**/.ssh/**", "**/.aws/**", "**/.gnupg/**",
    ])
    chunk_tokens: int = 400
    chunk_overlap: int = 40
    max_chunks_per_file: int = 60
    max_files_per_registration: int = 5000
    retrieval_file_limit: int = 6
    follow_symlinks: bool = False
    thumbs_dir: str = "~/.local/share/io/thumbs"   # Spec C
```

New runtime deps: **`pypdf`** (PDF text), **`python-docx`** (Word). Both pure
Python, offline. HTML is tag-stripped with a small regex (no `bs4`).

## 5. `io_assistant/files/` — modules

### 5.1 `paths.py` — the access gate (security-critical)

`AccessGate(config)` — the single authority every read passes through.

- `resolve(raw: str) -> Path` — expanduser, `Path(...).resolve()` (follows to an
  absolute real path), reject if it escapes to a non-existent parent.
- `key(path: Path) -> str` — the `path_key` (see 3.1).
- `is_allowed(path: Path, *, registered_keys: set[str]) -> bool` — **True** iff
  **all** of:
  - not matched by any `exclude_globs` pattern (checked against the full path,
    case-insensitive on Windows),
  - not a symlink unless `follow_symlinks`,
  - and (`key(path)` is in `registered_keys`, OR an ancestor's key is, OR the
    path is under one of `allowlist_roots`).
- `assert_allowed(path, *, registered_keys)` — raises `AccessDenied(path,
  reason)` otherwise.

`registered_keys` is loaded once per operation from
`SELECT path_key FROM file_nodes WHERE registered_root` (+ ancestors implicitly
via the "ancestor's key" check — a registered dir authorises everything under
it). Deny-by-default: an empty index + empty allowlist ⇒ nothing is readable.

### 5.2 `walk.py` — directory discovery

`walk_dir(root: Path, config, gate) -> Iterator[FoundPath]` — `os.walk` (or
`Path.rglob`), pruning excluded dirs, skipping symlinks unless allowed,
yielding files whose suffix is in `index_extensions ∪ media_extensions`, capped
at `max_files_per_registration` (raise `RegistrationTooLarge` with the count).
Returns `FoundPath(path, kind, mime, media_kind, size, mtime)`.

### 5.3 `extract.py` — text extraction by type

`read_document(path: Path, config) -> ExtractedDoc` where
`ExtractedDoc(text: str, title: str | None, truncated: bool, status: str,
error: str | None)`.

- size > `max_file_bytes` → `status="too_large"`, `text=""` (metadata still
  captured by the caller).
- `.pdf` → `pypdf`; `.docx` → `python-docx`; `.rtf` → strip control words with a
  regex; `.html`/`.htm`/`.xml` → regex tag strip + unescape; `.csv`/`.tsv` →
  first ~200 rows joined; everything else → read bytes, decode utf-8 (then
  latin-1 fallback); `UnicodeDecodeError` or a library error →
  `status="unreadable"`, `error=<short>`.
- `title` — first Markdown/HTML heading, else PDF metadata title, else `None`
  (caller falls back to the filename stem).

### 5.4 `chunk.py` — chunker

`chunk_text(text: str, *, chunk_tokens: int, overlap: int, max_chunks: int) ->
list[str]` — split on blank lines into paragraphs, greedily pack into
~`chunk_tokens` (`chars//4`) windows, carry `overlap` tokens of tail context
into the next, hard-split any single paragraph longer than the window, stop at
`max_chunks`. Deterministic and pure.

### 5.5 `index.py` — `FileIndexer` (index one node)

`FileIndexer(embedder, backend, config)`.
`index_path(session, path: Path, *, force: bool = False) -> FileNode`:

1. `stat`; if gone → upsert node `status="missing"`, return.
2. Compute `content_hash` (stream sha256). If `not force` and
   `index_hash == content_hash` and `status == "ok"` → **return unchanged**
   (the token-saver: no read, no embed, no model call).
3. `read_document`. On `too_large` / `unreadable` → upsert metadata + `status` +
   `error`, `index_hash = content_hash`, return.
4. `chunk_text` → embed each chunk **locally** (`embedder.embed`), replace this
   file's `file_chunks` rows.
5. `backend.summarize_file(title, head_text, mime=…)` where `head_text` is the
   first ~6000 characters of the extracted text → `{summary, entities,
   references}`. On `BackendParseError` → `summary = text[:200]`, `entities=[]`,
   `references=[]`.
6. Deterministic post-processing:
   - `summary` clipped to 400 chars; embed locally → `file_nodes.embedding`.
   - each `entities[i].name` → `EntityResolver.lookup(etype_or_scan, name)`;
     on a hit, upsert a `file_entity_link` (`source="summary"`, bump `mentions`).
     No creation. If `etype` is null, try person → place → item → occasion in
     order and take the first hit.
   - each `references[i]` string → look for a `file_nodes` row whose `path_key`
     ends with the normalised string or whose basename equals it; on a match,
     upsert a `references` edge (`detail=<string>`).
   - upsert the `contains` edge from the parent dir node (creating a bare parent
     `dir` node if absent).
7. Set `title`, `status="ok"`, `indexed_at=now()`, `index_hash=content_hash`.

### 5.6 `store.py` — `FileIndex` (DB store + graph)

`FileIndex(session_factory)`:

- `register(path: Path, *, gate) -> RegisterResult` — `assert_allowed`; upsert
  the node with `registered_at=now()`, `registered_root=True`; for a dir, also
  upsert bare child nodes from `walk_dir` (name/kind/mime/size/mtime only — **no
  content**); returns `{root, discovered: int, skipped: list}`.
- `get(path_key) -> FileNode | None`, `by_id(id)`.
- `stale(limit=None) -> list[FileNode]` — the staleness rule from 3.1, ordered
  by `registered_root DESC, mtime DESC`.
- `neighbors(file_id, rels: tuple[str,...], *, limit=20) -> list[FileNode]` —
  one hop over `file_edges` in either direction; `shares_entity` handled by the
  derived self-join on `file_entity_links`.
- `link_entity(file_id, etype, entity_id, *, source, detail=None)` — upsert +
  bump `mentions`.
- `add_edge(src_id, dst_id, rel, detail=None)` — upsert.
- `forget(path_key) -> int` — delete the `registered_root` node and every node
  whose `path_key` is under it (cascade takes chunks/edges/links); returns the
  count. Files on disk are untouched.
- `roots() -> list[FileNode]`, `status_summary() -> dict` (totals: nodes,
  indexed, stale, pending, errors, per-root breakdown).

### 5.7 `search.py` — `FileSearcher` (deterministic discovery → rank → phrase)

`FileSearcher(embedder, backend, config)`.
`search(session, question: str, now, *, context: str | None) -> FileAnswer`:

1. **Discovery** (no model):
   - *lexical* — `plainto_tsquery('english', question)` against `file_chunks.tsv`
     (top 30 by `ts_rank`), plus `ILIKE` on `file_nodes.title` / `path` /
     `summary`.
   - *semantic* — `embedder.embed_one(question)`; cosine-KNN over
     `file_chunks.embedding` (30) and `file_nodes.embedding` (15).
   - *entity* — `resolve_query_entities()` (the existing read-only helper);
     pull `file_entity_links` for the resolved ids.
   - *graph expansion* — for the union of the top hits so far, `FileIndex.
     neighbors(rels=("contains","references","shares_entity"))`, one hop; add
     with a provenance tag `neighbor`.
2. **Rank** (deterministic, mirrors `query/rank.py`):
   `score = 0.30·recency(mtime) + 0.30·max_chunk_similarity +
   0.20·lexical_rank + 0.15·entity_link + 0.05·neighbor_bonus`.
   `recency = exp(-age_days/45)`. Keep the top `retrieval_file_limit`.
3. **Freshness pass** — for each kept node: `stat` it; if the path is gone →
   `status="missing"`, drop; if `content_hash` changed or `status != "ok"` →
   `FileIndexer.index_path(force=False)` now (lazy re-index of *only* what we're
   about to use), then re-pull its best chunks.
4. **Answer** — if nothing survived: deterministic
   `FileAnswer(text="I don't have any files that cover that yet.", …)` — **no
   model call**. Otherwise
   `backend.answer_from_files(question,
   [{path, title, summary, excerpts: <=3 best chunks}], shape, context=context)`.
5. Return `FileAnswer(text, shape, hits: list[FileHit], searched: int)` where
   `FileHit(path, title, why, media_kind)` and `why` is a short deterministic
   string (`"matches “lease pets”"`, `"same folder as bill.pdf"`,
   `"mentions Nafay"`).

### 5.8 `command.py` — deterministic file-command classification

`classify_file_command(text: str) -> FileCommand` where
`FileCommand(action: Literal["register","search"], path: str | None,
phrase: str | None)`:

- an explicit path substring (regex: `([A-Za-z]:\\[^"\n]+ | /[^"\n]+ |
  ~[/\\][^"\n]+)`) ⇒ `path` set.
- a **register verb** near the start (`remember`, `index`, `register`, `keep
  track of`, `watch`, `add … to (your|my) files`) ⇒ `action="register"`;
  `phrase` = the noun phrase after the verb when no explicit `path`.
- otherwise ⇒ `action="search"`.

`resolve_register_target(phrase: str, session, gate, config) ->
ResolveResult` — fuzzy-match `phrase` (rapidfuzz, already a dep) against the
basenames of: registered `dir` nodes, and directories one scandir level below
each `allowlist_root`. `ResolveResult` is `one(path)`, `many(list[Path])`, or
`none()`.

## 6. Backend additions

`io_assistant/backend/interface.py` `Backend` Protocol gains:

```python
def summarize_file(self, title: str, head_text: str, *,
                   mime: str | None = None) -> dict: ...
    # -> {"summary": str,
    #     "entities": [{"etype": "person|place|item|occasion|null", "name": str}],
    #     "references": [str]}          # raises BackendParseError on bad JSON

def answer_from_files(self, question: str, files: list[dict], shape: str,
                      *, context: str | None = None) -> str: ...
    # files: [{"path", "title", "summary", "excerpts": [str]}]
```

- Prompts: `io_assistant/prompts/file_summary.txt`,
  `io_assistant/prompts/file_answer.txt`. `file_answer.txt` carries the same
  `{context}` slot convention as `respond.txt`; it instructs: answer **only**
  from the supplied summaries and excerpts, cite file paths in the answer, say
  plainly when the material does not contain the answer, never invent.
- `local.py` / `anthropic_backend.py` / `hybrid.py` all implement both. Hybrid:
  `summarize_file` → local (it is bulk + frequent), `answer_from_files` → cloud
  (matches `phrase`). Anthropic `answer_from_files` `max_tokens = 500`,
  `summarize_file` `max_tokens = 300`.
- `tests/conftest.py::FakeBackend` gains `summarize_file` / `answer_from_files`
  returning canned values, with `set_file_summary(...)` / `set_file_answer(...)`
  setters and `last_*` capture, matching the existing pattern.

## 7. Orchestrator integration

- `models_domain.Intent` → `Literal["store", "query", "file", "unknown"]`.
  `prompts/route.txt` gains a `FILE` class + examples (*"remember my Taxes
  folder in Documents"*, *"what does my lease say about pets"*, *"find the
  Granjur invoice"*, *"open the notes from the Hunza trip"*). Extend
  `tests/fixtures/utterances_route.json`; keep the opt-in accuracy threshold
  realistic for `llama3.2:3b` (note in the plan).
- `models_domain` gains `FileHit` + `FilesCard`
  (`type="files"`, `hits: list[FileHit]`, `searched: int`);
  `Card = RecordCard | TaskListCard | SourcesCard | FilesCard`.
- `Orchestrator.__init__`: when `config.files.enabled`, build
  `self._files = FileSearcher(...)`, `self._file_index = FileIndex(factory)`,
  `self._indexer = FileIndexer(...)`; else all `None`.
- `_handle_in_session`, after routing:

```python
if intent == "file":
    session.add(m.Utterance(text=text, source=source, captured_at=captured_at,
                            resolved_intent="file"))
    session.flush()
    if not self._config.files.enabled:
        return HandleResult("file", None,
            "I can't open files yet — enable [files] in config.toml first.",
            intent_kind="unknown")
    cmd = classify_file_command(text)
    if cmd.action == "register":
        return self._file_register(session, cmd, now)
    answer = self._files.search(session, text, now, context=history)
    return HandleResult("file", None, answer.text,
        cards=[files_card(answer)], intent_kind="files", shape=answer.shape)
```

- `_file_register`: resolve `cmd.path` (explicit) or
  `resolve_register_target(cmd.phrase, …)`.
  - `one(path)` → `FileIndex.register(path)`, enqueue indexing (or index inline
    for a single small file), return `HandleResult("file", None,
    "Indexing <name> now — N files.", intent_kind="ack")`.
  - `many` → `HandleResult(..., "I found a few — which one? <list>",
    intent_kind="unknown")` (no gate/pending in v1).
  - `none` / `AccessDenied` → a plain explanatory message, `intent_kind`
    `"unknown"` / `"error"`.
- `HandleResult` already carries `cards` + `intent_kind` + `shape`; no shape
  change. The service maps `intent_kind="files"` to a message `kind` the same
  way it maps `"answer"`/`"ack"`.

## 8. Service

All new routes return **404** when `config.files.enabled` is false.

| route | body / query | returns |
|---|---|---|
| `POST /files` | `{path}` | `{root, discovered, skipped}` — `assert_allowed` first (400 `AccessDenied`), then `FileIndex.register`, then enqueue |
| `GET /files` | — | `{enabled, roots: [{path, kind, files, indexed, stale, errors}]}` |
| `DELETE /files` | `{path}` | `{forgotten: <count>}` |
| `POST /files/reindex` | `{path?}` | force-reindex a subtree, or all stale; `{queued: <count>}` |
| `GET /files/status` | — | `FileIndex.status_summary()` + `{queue_depth}` |
| `GET /files/content` | `?path=` | `{path, title, text}` — extracted text capped at ~20 k chars, for the in-app viewer; `assert_allowed`, 404 if missing/unreadable |

**Background index worker** — `io_assistant/files/queue.py`:
`IndexQueue(session_factory, indexer)` wraps a `queue.Queue[str]` + one daemon
thread. `create_app` starts it iff `config.files.enabled`; `enqueue(path)` /
`enqueue_many`. The worker pulls a path, opens a session, calls
`indexer.index_path`, commits, loops. Concurrency 1. On app shutdown the thread
is asked to stop and joined with a short timeout. `GET /files/status` reports
`queue_depth = q.qsize()`.

CLI `io files` operations run the indexer **synchronously** in-process (no
service needed).

## 9. CLI — `io files` sub-app

A `typer` sub-app mounted on the main `app`:

- `io files add <path> [--no-index]` — register + (unless `--no-index`) index
  synchronously with a progress line; prints the cloud-boundary notice once when
  `backend.provider != "local"`.
- `io files list` — roots + counts.
- `io files reindex [<path>] [--all-stale]` — force.
- `io files forget <path>` — unregister (index only; disk untouched) with a
  confirm prompt.
- `io files search <query...>` — run `FileSearcher`, print the answer then the
  hit list (path · why). For testing without the GUI.
- `io files status` — the status summary.

## 10. Frontend

### 10.1 Files view (`frontend/views/files.js`)

Reached from a new **Files** rail button (Phosphor `folders` / `folder`). Shows:

- registered roots, each a row: name, path (dim, `mono`), status chips
  (`N indexed` / `M stale` / `E errors`), a **Reindex** and a **Remove** icon
  button.
- an **Add path** affordance: a text input + button → `POST /files`; on a 400
  it shows the `AccessDenied` reason inline.
- polls `GET /files/status` every few seconds while the queue is non-empty so
  progress is visible.

### 10.2 `files` card (`frontend/components/card.js`)

New branch for `card.type === "files"`: a titled list; each hit is
`title` (or filename) + `path` (`mono`, dim) + `why` (dim). Clicking a hit
fetches `GET /files/content` and shows the extracted text in the inspector slot
(reusing the Conversation view's `#inspector`), with the path as a header. A
hit with `media_kind` set shows a small type glyph and, in Spec C, opens the
media viewer instead.

### 10.3 Assets

No new vendored assets — the `folders`/`folder`/`file` glyphs are added to
`frontend/vendor/icons.js` from the already-in-repo Phosphor set.

## 11. Testing

Real PostgreSQL for every DB test; `FakeBackend` for model calls; `tmp_path`
for filesystem fixtures. New fixture dir `tests/fixtures/files/` with a tiny
real `sample.pdf`, `sample.docx`, `notes.md`, `data.csv`, `binary.bin`.

| file | covers |
|---|---|
| `tests/test_files_paths.py` | the gate: registered / ancestor / allowlist allow; outside, excluded-glob, symlink, `..`-escape deny; Windows case-fold dedup |
| `tests/test_files_chunk.py` | window size, overlap, hard-split, `max_chunks`, empty input |
| `tests/test_files_extract.py` | each type reads; `too_large` keeps metadata; undecodable → `unreadable` |
| `tests/test_files_store.py` | register file/dir; lazy child nodes; `stale()`; `neighbors()` both directions + `shares_entity`; `link_entity` bump; `forget` cascade |
| `tests/test_files_index.py` | chunks+embeddings+summary written; **re-index with same hash is a no-op** (backend/embedder not called again); entities linked only on resolver hit; `references` string → edge; `summarize_file` parse error → fallback summary, `status="ok"` |
| `tests/test_files_search.py` | discovery returns expected ids; graph expansion adds siblings; rank order; freshness pass re-indexes a changed file before answering; `retrieval_file_limit` enforced; empty → deterministic no-model answer |
| `tests/test_files_command.py` | explicit Win/POSIX/`~` paths; register verbs vs search phrasing; phrase extraction |
| `tests/test_orchestrator_files.py` | `file` + register phrase → `register` + ack; `file` + question → `FilesCard`; `enabled=False` → polite refusal; an `utterances` row with `resolved_intent="file"` is written |
| `tests/test_service_files.py` | `POST /files` allow/deny; `GET/DELETE /files`; `/files/reindex`; `/files/content`; a `file` turn via `/utterance` returns a `files` card; every route 404s when disabled |
| `tests/test_e2e_store.py` | socket guard still green (no new outbound) |
| `tests/test_frontend_assets.py` | new JS passes `node --check`; still no external URLs |
| `tests/test_router_*` (opt-in) | `FILE` examples added to the fixture; threshold noted |

## 12. Risks & decisions

- **Windows path case-insensitivity** → `path_key` column; the gate lower-cases
  on Windows only.
- **Big registrations** → `max_files_per_registration` cap; `walk.py` raises
  with the count; the CLI/route surface the number and register nothing.
- **Cloud file text** → user-approved; enforced-visible via config comment +
  `io files add` notice; embeddings stay local regardless.
- **No entity creation from summaries** → link-on-resolve only; keeps the
  people/places tables clean. Creation is a Spec C (caption) concern.
- **FTS language** fixed to `english` for v1.
- **Router load** — a 4th class on a marginal 3B classifier. Mitigation: one
  coarse `file` class (not `file_register` + `file_search`), the register/search
  split is deterministic, and the fixture + threshold are tuned in the plan.
- **`resolved_intent` values** — doc-comment in `data-model.md` updated to list
  `file`.

## 13. Open follow-ups (backlog after Spec A)

- Agentic exploration loop (escalate when `FileSearcher` is low-confidence).
- `query` ↔ `file` cross-fallback in one turn.
- Filesystem watching / scheduled re-index instead of lazy hash checks.
- Learned co-retrieval edges.
- Index-time OCR for scanned PDFs.
- `references`-edge resolution is substring-based; upgrade to a proper path
  parser if it proves noisy.
