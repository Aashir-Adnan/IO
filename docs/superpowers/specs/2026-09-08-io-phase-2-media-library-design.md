# IO Phase 2 · Spec C — Media Library & Captioning

> Depends on **Spec A** (`…-io-phase-2-file-index-design.md`) — it reuses
> `file_nodes`, `file_entity_links`, the `AccessGate`, and the `file` router
> intent. Build after Spec A.

## 1. Vision & scope

> *"Hey IO, open the folder called 'Hunza Trip 2026'."*
> IO shows an in-app gallery of the photos and videos in that folder. You pick
> one, and a box says **"Tell me about this picture / video."** You type or
> speak *"That's me and Nafay at Attabad Lake."* IO links the photo to **Nafay**
> (person) and **Attabad Lake** (place), and remembers.

The captions are **user-authored ground truth** — IO never guesses what is in a
photo. The only model call is IO's existing entity extraction over the caption
sentence (exactly the `extract` boundary), followed by the normal resolver +
confirmation gate. No vision model, no frame analysis.

### In scope

- `classify_file_command` gains an **`open`** action; folder resolution by name.
- An in-app **gallery view**: thumbnail grid → detail pane with a full-size
  `<img>` or a streaming `<video controls>` player.
- A **caption box** (type or speak) per media item → `POST /files/caption` →
  entity extraction → `file_entity_links` (+ create/gate entities like STORE
  does) → caption embedded so *"photos of Nafay"* is searchable via Spec A.
- Thumbnail generation (`Pillow`) + local media serving with HTTP range.
- `file_captions` history table (migration `0005`); `file_nodes.caption` /
  `media_kind` / `thumb_path` / `captured_at` populated for media.

### Out of scope (backlog)

- Video frame-grab thumbnails (needs `ffmpeg`) — v1 uses a film glyph.
- Face/object detection, auto-tagging, reverse image search.
- Editing / deleting the underlying media files.
- EXIF GPS → `Place` resolution (store `captured_at` only for now).

## 2. Global constraints

Inherits every constraint from Spec A §2. Additionally:

- Media bytes are served **only** through `GET /files/raw` / `GET /files/thumb`,
  both behind `AccessGate.assert_allowed`. No directory listing endpoint beyond
  the resolved-folder gallery payload.
- Thumbnails live under `files.thumbs_dir` (`~/.local/share/io/thumbs/`), named
  by `sha256(path_key)[:16] + ".webp"`. Never written next to the original.
- Caption text follows the same cloud rule as file text (Spec A §2): entity
  extraction over a caption uses the configured backend.

## 3. Data model — migration `0005_file_captions`

`file_nodes` columns from Spec A 3.1 (`caption`, `media_kind`, `captured_at`)
are already present; this migration adds **`thumb_path Text NULL`** to
`file_nodes` and one new table:

### `file_captions`

| column | type | notes |
|---|---|---|
| `id` | BigInteger PK | |
| `file_id` | BigInteger FK `file_nodes` ON DELETE CASCADE, NOT NULL | |
| `text` | Text NOT NULL | verbatim, user-authored |
| `source` | String(8) NOT NULL | `text` \| `voice` |
| `created_at` | DateTime(tz), server default `now()` | |

Index: b-tree `(file_id, created_at)`.

`file_nodes.caption` mirrors the **latest** caption (for quick display + the
embedding); `file_captions` keeps the full history. `file_nodes.embedding` for a
media node is the embedding of `caption` (NULL until first captioned).

ORM: `FileCaption` appended to `models.py`; `thumb_path` added to `FileNode`.

## 4. `io_assistant/files/` additions

### 4.1 `command.py` — `open` action

`classify_file_command` returns `action ∈ {"register","search","open"}`.
`open` when an **open verb** (`open`, `show`, `show me`, `browse`, `go to`,
`pull up`) precedes a folder reference and there is no register verb.
`phrase` carries the folder name.

`resolve_folder(phrase, session, gate, config) -> ResolveResult` — fuzzy-match
`phrase` (rapidfuzz) against basenames of: registered `dir` nodes, then
directories found by a bounded `rglob` (depth ≤ 3, capped) under each
`allowlist_root` and each registered dir. `one` / `many` / `none` like
`resolve_register_target`.

### 4.2 `thumbs.py`

`make_thumb(path: Path, media_kind: str, out_dir: Path) -> Path | None`:

- `image` → `PIL.Image.open`, `exif_transpose`, `.thumbnail((512, 512))`, save
  `.webp` quality 80. HEIC: try `pillow-heif` (optional dep); on `ImportError`
  return `None`.
- `video` → `None` in v1 (frontend shows a film glyph).
- any failure → `None`, logged; caller sets `status` unchanged (`ok`) but leaves
  `thumb_path` NULL.

`exif_captured_at(path) -> datetime | None` — `PIL` EXIF `DateTimeOriginal`,
parsed to an aware UTC datetime; best-effort.

### 4.3 `index.py` — media branch

`FileIndexer.index_path` already stores metadata for any node. For a node whose
suffix is in `media_extensions`:

- set `media_kind`; `content_hash` from bytes; `captured_at` from
  `exif_captured_at`; `thumb_path` from `make_thumb` (best-effort).
- **no** `read_document`, **no** `file_chunks`, **no** `summarize_file`.
- `status="ok"`, `index_hash=content_hash`. `embedding` stays NULL until a
  caption exists.

### 4.4 `gallery.py`

`open_folder(session, folder: Path, *, gate, indexer, config) -> GalleryPayload`:

1. `assert_allowed(folder)`.
2. `walk_dir` for media files; ensure a `file_nodes` row for each (register the
   folder as a `registered_root` dir if it is not already under one), index any
   that are `pending`/stale (metadata + thumb only — fast).
3. Return `GalleryPayload(folder_path, count, items: list[GalleryItem])` where
   `GalleryItem(path, media_kind, thumb_url, has_thumb, caption,
   entities: list[EntityRef], captured_at)`.
   `thumb_url = f"/files/thumb?path=…"`, raw URL `/files/raw?path=…`.

### 4.5 `caption.py`

`apply_caption(session, path: Path, text: str, source: str, *, gate, extractor,
resolver, embedder) -> CaptionResult`:

1. `assert_allowed`; load / create the media `file_nodes` row.
2. insert a `file_captions` row; set `file_nodes.caption = text`.
3. `extractor.run(text, now)` → people / places / items / occasions (records in
   the extraction are **ignored** — a caption never creates a `records` row).
4. for each extracted entity: `resolver.resolve(...)` **with the confidence
   gate** (same call STORE uses — it creates new entities and gates on low
   confidence). If any resolve gates → return
   `CaptionResult(gated=True, gate_reasons=[…], pending=PendingCaption(file_id,
   text, extraction))`.
5. otherwise upsert `file_entity_links` (`source="caption"`, bump `mentions`)
   for every resolved id.
6. embed `text` locally → `file_nodes.embedding` (media node becomes searchable
   through Spec A's `FileSearcher`).
7. return `CaptionResult(gated=False, entities=[EntityRef…], caption=text)`.

## 5. Orchestrator & pending

- `_handle_in_session` `file` branch: `cmd.action == "open"` →
  `_file_open(session, cmd, now)` → resolve the folder →
  - `one` → `HandleResult("file", None, "Opening <name> — N items.",
    cards=[gallery_card(payload)], intent_kind="gallery")`.
  - `many` / `none` → explanatory message.
- New `models_domain` card:
  `GalleryCard(type="gallery", folder_path: str, count: int,
  items: list[GalleryItem])`; `GalleryItem` as in 4.4.
  `Card = … | FilesCard | GalleryCard`.
- **`PendingCaption`** — a second pending type alongside `PendingStore`.
  `Orchestrator.handle(pending=…)` and the service's `app.state.pending`
  (`dict[str, PendingStore | PendingCaption]`) dispatch on type. Confirming a
  `PendingCaption` replays steps 5–7 of `apply_caption` with `confirmed=True`.
- Captions submitted from the gallery UI go through a **dedicated route**
  (`POST /files/caption`), not `/utterance` — but a gate still returns a
  `pending_token` the UI resolves with `POST /files/caption/confirm`.

## 6. Service

| route | body / query | returns |
|---|---|---|
| `GET /files/thumb` | `?path=` | the `.webp` thumb (generate-on-miss); 302→a generic glyph route or 404 when `thumb_path` is NULL |
| `GET /files/raw` | `?path=` | the original bytes, `FileResponse` with **HTTP Range** support (206 + `Content-Range` for video seeking); `assert_allowed` |
| `POST /files/open` | `{path}` or `{phrase}` | `GalleryPayload` (resolve a phrase server-side; 409 with candidates on `many`) |
| `POST /files/caption` | `{path, text, source}` | `{entities:[EntityRef], caption}` or `{gated:true, reasons:[…], pending_token}` |
| `POST /files/caption/confirm` | `{pending_token}` | `{entities, caption}` |

All 404 when `config.files.enabled` is false. Range handling: use Starlette's
`FileResponse` (it honours `Range`) or a small explicit responder for
`video/*`; add a test asserting a `Range: bytes=0-1023` request yields `206`
with a correct `Content-Range`.

## 7. Frontend — gallery view

### 7.1 `frontend/views/gallery.js`

`mount(root, ctx)` renders from a `GalleryCard` (passed via
`ctx.store` / the turn) or by calling `ctx.api.openFolder(pathOrPhrase)`:

- **grid** — CSS `grid` of tiles, `aspect-ratio: 1`, lazy `<img
  loading="lazy" src=thumb_url>`; video tiles overlay a play glyph; a tile with
  `has_thumb=false` shows a centered file/film glyph on `--color-panel`.
- **detail pane** (right, or a modal on narrow widths) — opens on tile click:
  - image → `<img src="/files/raw?path=…">`, fit-contain.
  - video → `<video controls preload="metadata" src="/files/raw?path=…">`
    (range requests make seeking work).
  - **caption box** — a `Composer`-style textarea (reuse `components/composer.js`
    with `compact`) + mic button, placeholder *"Tell me about this
    picture / video"*. Submit → `ctx.api.caption(path, text, source)`.
    - success → the pane shows the caption and entity chips (person/place/…),
      each chip opening the Memory Inspector (`ctx.openInspector`, already exists).
    - `{gated:true}` → an inline confirm row (*"Create new person 'Nafay'?
      Yes / edit"*) → `ctx.api.captionConfirm(token)`.
  - voice caption: the mic uses the existing `WavRecorder`; audio is transcribed
    by the existing `POST /voice` transcribe path? — simplest: the gallery mic
    posts the WAV to a tiny `POST /files/caption` variant with `audio` multipart
    that transcribes then applies. To avoid a second transcribe endpoint, v1
    records → `POST /voice` **with a flag `transcribe_only=1`** returning just
    `{transcript}` → the UI drops that into the caption box for the user to
    confirm/edit → normal `POST /files/caption`. (Add `transcribe_only` to
    `/voice`.)

### 7.2 Entering the gallery

- Voice/text: *"open the folder called X"* → turn returns a `gallery` card →
  `app.js` routes to the gallery view with that payload.
- From the **Files** view (Spec A 10.1): each registered `dir` root gets an
  **Open** button → `ctx.api.openFolder(path)` → gallery view.
- Rail: no new button; the gallery is a destination of the Files view and of a
  turn.

### 7.3 Assets

Add `image`, `video`/`filmSlate`, `play` glyphs to `vendor/icons.js` from the
in-repo Phosphor set. No other new assets. `<video>`/`<img>` stream from the
local service — no CDN, socket guard unaffected.

## 8. Testing

New fixtures: `tests/fixtures/files/pic.jpg` (tiny, with an EXIF date),
`tests/fixtures/files/clip.mp4` (a ~1 s clip).

| file | covers |
|---|---|
| `tests/test_files_command_open.py` | `open` verb detection; `resolve_folder` one/many/none, fuzzy |
| `tests/test_files_thumbs.py` | `make_thumb` produces a valid ≤512 webp from `pic.jpg`; video → `None`; corrupt image → `None`; `exif_captured_at` parses |
| `tests/test_files_index_media.py` | a media node gets `media_kind` / `content_hash` / `thumb_path` / `captured_at`, **no chunks**, `embedding` NULL pre-caption |
| `tests/test_files_gallery.py` | `open_folder` registers the dir, lists media, builds `thumb_url`s, indexes pending items |
| `tests/test_files_caption.py` | caption row + `file_nodes.caption` set; entities extracted → `file_entity_links` (`source="caption"`); low-confidence → gated + `PendingCaption`; confirm replays; caption embedded (node now returned by `FileSearcher` for a matching query); **no `records` row created** |
| `tests/test_service_media.py` | `GET /files/raw` Range → 206 + `Content-Range`; `GET /files/thumb` generate-on-miss; `POST /files/open` (path + phrase, 409 on many); `POST /files/caption` + `/confirm`; all 404 when disabled |
| `tests/test_orchestrator_files.py` (extend) | `open` folder phrase → `gallery` card; `PendingCaption` dispatch through `handle` |
| `tests/test_frontend_smoke.py` (extend, opt-in) | gallery grid renders tiles; a `<video>` element is present for a video item; caption box submits |
| `tests/test_e2e_store.py` | socket guard green |

## 9. Risks & decisions

- **Second pending type** (`PendingCaption`) — accepted cost; keeps caption
  entity-creation on the same safe resolver+gate path as STORE.
- **Voice captions** reuse `/voice` with `transcribe_only=1` rather than a new
  ASR endpoint.
- **HEIC** — optional `pillow-heif`; graceful glyph fallback when absent.
- **Video thumbnails** deferred (ffmpeg dependency); film glyph in the interim.
- **Large folders** — the gallery payload is capped
  (`max_files_per_registration`); the grid paginates client-side.
- **Range requests** — lean on Starlette `FileResponse`; explicit test.
- Captions are **replace-latest** on `file_nodes.caption` with full history in
  `file_captions`; re-embedding uses only the latest.
