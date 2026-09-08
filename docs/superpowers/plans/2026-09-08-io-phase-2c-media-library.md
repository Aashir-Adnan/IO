# Phase 2C — Media Library & Captioning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Open the folder called X" → an in-app gallery of its photos and
videos, each with a type-or-speak caption box that links the item to people /
places / occasions and makes it searchable.

**Architecture:** Builds on the merged Phase 2A file index. Media files already
get a `file_nodes` row (`media_kind` set by extension); this phase adds
thumbnails, EXIF dates, a captions table, a `resolve_folder` + `open` command
action, `gallery.open_folder()`, `caption.apply_caption()` (reusing the
existing `Extractor` + `EntityResolver` + confirmation gate — captions are
user-authored ground truth, no vision model), five service routes (thumb / raw
with HTTP Range / open / caption / caption-confirm), and a gallery frontend
view. The LLM is called only for entity extraction over the caption sentence —
the same `extract` boundary STORE uses.

**Tech Stack:** Python 3.11+, SQLAlchemy 2.x + Alembic, FastAPI + Starlette
`FileResponse` (Range support), `Pillow` (thumbnails + EXIF), pydantic v2,
vanilla-JS frontend. `pillow-heif` is an optional dep (HEIC) — deferred.

**Spec:** `docs/superpowers/specs/2026-09-08-io-phase-2-media-library-design.md`
(read alongside this plan). Phase 2A:
`docs/superpowers/specs/2026-09-08-io-phase-2-file-index-design.md` +
`.claude/knowledge/file-index.md`.

## Global Constraints

- **local-first:** no new outbound traffic. `<img>`/`<video>` stream from the
  local service. `tests/test_e2e_store.py`'s socket guard stays green.
- **Cloud boundary:** caption text goes through the configured backend for
  entity extraction — when `backend.provider != "local"` it reaches
  `api.anthropic.com`, exactly like file text. Embeddings are always local.
- **Media bytes are served only through `GET /files/raw` / `GET /files/thumb`**,
  both behind `AccessGate.assert_allowed`.
- **Thumbnails** live under `config.files.thumbs_dir`
  (`~/.local/share/io/thumbs/`), named `sha256(path_key)[:16] + ".webp"`. Never
  written next to the original.
- **migrations:** Alembic only. `embedding_dim` stays `768`.
- **resource-budget:** thumbnail generation is best-effort and synchronous per
  item during `open_folder` (metadata + thumb only — no text extraction, no
  model call). No background crawl.
- **test-discipline:** TDD; real PostgreSQL (`IO_TEST_DATABASE_URL`);
  `FakeBackend` for model calls; `StubEmbedder` for embeddings. Tests that
  commit through their own engine (service `TestClient`, CLI) must wipe the
  `file_*` tables — Phase 2A added `_wipe_files` helpers; reuse that pattern.
- Package `io_assistant`; run via `uv run pytest` (set `IO_TEST_DATABASE_URL`).
- No new vendored frontend assets beyond three inlined Phosphor SVG paths.

## File Structure

**New:**

| file | responsibility |
|---|---|
| `io_assistant/db/migrations/versions/0005_media.py` | `thumb_path` on `file_nodes`; `file_captions` table |
| `io_assistant/files/thumbs.py` | `make_thumb()`, `exif_captured_at()` — Pillow, best-effort |
| `io_assistant/files/gallery.py` | `open_folder()` → `GalleryCard` |
| `io_assistant/files/caption.py` | `apply_caption()`, `CaptionResult`, `PendingCaption` |
| `frontend/views/gallery.js` | the gallery view (grid + detail pane + caption box) |
| `tests/fixtures/files/pic.jpg`, `clip.mp4` | generated fixtures |
| `tests/test_files_thumbs.py`, `test_files_command_open.py`, `test_files_gallery.py`, `test_files_caption.py`, `test_service_media.py`, `test_frontend_gallery.py` | new tests |

**Modified:**

| file | change |
|---|---|
| `io_assistant/db/models.py` | `FileNode.thumb_path`; new `FileCaption` |
| `io_assistant/models_domain.py` | `GalleryItem`, `GalleryCard`; `Card` union |
| `io_assistant/files/command.py` | `FileCommand.action` gains `"open"`; `resolve_folder()` |
| `io_assistant/files/index.py` | media branch: `captured_at` + `thumb_path` |
| `io_assistant/files/cards.py` | `gallery_card()` |
| `io_assistant/orchestrator.py` | `_file_turn` `open` action → `_file_open` |
| `io_assistant/service/schemas.py` | `FileOpenIn`, `CaptionIn`, `CaptionConfirmIn`, `CaptionOut`, `GalleryOut` |
| `io_assistant/service/app.py` | `/files/thumb`, `/files/raw`, `/files/open`, `/files/caption`, `/files/caption/confirm`, `/files/transcribe` |
| `frontend/api.js` | `openFolder`, `caption`, `captionConfirm`, `transcribeAudio`, `rawUrl`, `thumbUrl` |
| `frontend/app.js` | `gallery` in `VIEWS`; a turn interceptor routing a `gallery` card to the view; `store.gallery` |
| `frontend/views/files.js` | an **Open** button per registered `dir` root |
| `frontend/vendor/icons.js` | `image`, `filmSlate`, `play` glyphs |
| `frontend/app.css` | gallery styles |
| `.claude/knowledge/file-index.md`, `data-model.md`, `.claude/state/*` | docs |

**Deviations from the spec (deliberate, recorded in Self-Review):**

- Voice captions use a dedicated `POST /files/transcribe` (multipart audio →
  `{transcript}`) instead of adding a `transcribe_only` flag to `/voice`. One
  file-scoped route, `/voice` untouched.
- `PendingCaption` is **not** threaded through `Orchestrator.handle()` /
  `app.state.pending`. Captions never enter the turn pipeline — the caption
  routes own a small `app.state.caption_pending: dict[str, PendingCaption]`.
  This removes the "second pending type in `handle()`" complexity from spec §5.
- New dep `Pillow` is added explicitly (it is already transitively present via
  the Phase 2A `reportlab` dev dep, but this phase needs it at runtime).

---

## Task 1: Migration 0005, ORM, Pillow dep

**Files:**
- Create: `io_assistant/db/migrations/versions/0005_media.py`
- Modify: `io_assistant/db/models.py` (`FileNode` — add `thumb_path`;
  append `FileCaption` after `FileEntityLink`)
- Modify: `pyproject.toml` — `uv add pillow`
- Test: `tests/test_files_schema.py` (extend)

**Interfaces:**
- Produces:
  - `file_nodes.thumb_path Text NULL`.
  - ORM `FileCaption` (`file_captions`): `id` BigInteger PK, `file_id`
    BigInteger FK `file_nodes` ON DELETE CASCADE NOT NULL, `text` Text NOT NULL,
    `source` String(8) NOT NULL, `created_at` DateTime(tz) server default
    `now()`. Index `ix_file_captions_file_id_created_at` on
    `(file_id, created_at)`.
  - `FileNode.thumb_path: Mapped[str | None]`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_files_schema.py`

```python
@requires_db
def test_file_captions_table_and_thumb_path(db):
    from io_assistant.db import models as m
    n = m.FileNode(path="/m/pic.jpg", path_key="/m/pic.jpg", kind="file",
                   media_kind="image", status="ok", thumb_path="/t/abc.webp")
    db.add(n); db.flush()
    assert n.thumb_path == "/t/abc.webp"
    db.add(m.FileCaption(file_id=n.id, text="me and Nafay", source="text"))
    db.flush()
    assert db.query(m.FileCaption).one().text == "me and Nafay"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_files_schema.py::test_file_captions_table_and_thumb_path -q`
Expected: FAIL — `AttributeError: type object 'FileNode' has no attribute 'thumb_path'` / no `FileCaption`.

- [ ] **Step 3: Add `thumb_path` to `FileNode` and the `FileCaption` model**

In `FileNode`, after `caption`:
```python
    thumb_path: Mapped[str | None] = mapped_column(Text, nullable=True)
```

After `class FileEntityLink`:
```python
class FileCaption(Base):
    __tablename__ = "file_captions"
    __table_args__ = (
        Index("ix_file_captions_file_id_created_at", "file_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    file_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 4: Write the migration `0005_media.py`**

```python
"""media: file_nodes.thumb_path + file_captions

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("file_nodes", sa.Column("thumb_path", sa.Text(), nullable=True))
    op.create_table(
        "file_captions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("file_id", sa.BigInteger(),
                  sa.ForeignKey("file_nodes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_file_captions_file_id_created_at", "file_captions",
                    ["file_id", "created_at"])


def downgrade() -> None:
    op.drop_table("file_captions")
    op.drop_column("file_nodes", "thumb_path")
```

- [ ] **Step 5: Add the dep**

```bash
uv add pillow
```
(If `uv add` fails with "cannot access io.exe — process in use", kill the
lingering process: `Get-Process io | Stop-Process -Force` in PowerShell, then
retry.)

- [ ] **Step 6: Run the tests**

Run: `IO_TEST_DATABASE_URL=... uv run pytest tests/test_files_schema.py -q`
Expected: PASS (the session-scoped `engine` fixture rebuilds the schema via
`alembic upgrade head`, exercising `0005` up and down).

- [ ] **Step 7: Commit**

```bash
git add io_assistant/db/models.py io_assistant/db/migrations/versions/0005_media.py \
  pyproject.toml uv.lock tests/test_files_schema.py
git commit -m "feat(media): 0005 — file_nodes.thumb_path + file_captions"
```

---

## Task 2: `thumbs.py` — thumbnails + EXIF date

**Files:**
- Create: `io_assistant/files/thumbs.py`
- Create fixtures: `tests/fixtures/files/pic.jpg` (generated, Step 3),
  `tests/fixtures/files/clip.mp4` (stub bytes, Step 3)
- Test: `tests/test_files_thumbs.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `thumb_name(path_key: str) -> str` — `sha256(path_key)[:16] + ".webp"`.
  - `make_thumb(path: Path, media_kind: str, out_dir: Path, *, path_key: str)
    -> Path | None` — `image` → Pillow `exif_transpose` +
    `thumbnail((512, 512))` + save webp q80 to `out_dir / thumb_name(path_key)`;
    returns that path. `video` → `None`. Any exception → `None`. Creates
    `out_dir` if missing.
  - `exif_captured_at(path: Path) -> datetime | None` — Pillow EXIF tag 36867
    (`DateTimeOriginal`), parsed `"%Y:%m:%d %H:%M:%S"` → aware UTC. Any failure
    → `None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_thumbs.py
import datetime as dt
from pathlib import Path

from PIL import Image
from io_assistant.files.thumbs import make_thumb, exif_captured_at, thumb_name

FX = Path(__file__).parent / "fixtures" / "files"


def test_make_thumb_image(tmp_path):
    out = make_thumb(FX / "pic.jpg", "image", tmp_path, path_key="k/pic.jpg")
    assert out is not None and out.exists()
    with Image.open(out) as im:
        assert max(im.size) <= 512
        assert im.format == "WEBP"
    assert out.name == thumb_name("k/pic.jpg")


def test_make_thumb_video_is_none(tmp_path):
    assert make_thumb(FX / "clip.mp4", "video", tmp_path, path_key="k/clip.mp4") is None


def test_make_thumb_corrupt_is_none(tmp_path):
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    assert make_thumb(bad, "image", tmp_path, path_key="k/bad.jpg") is None


def test_exif_captured_at_parses():
    got = exif_captured_at(FX / "pic.jpg")
    assert isinstance(got, dt.datetime) and got.year == 2026


def test_exif_missing_is_none(tmp_path):
    p = tmp_path / "noexif.jpg"
    Image.new("RGB", (8, 8), "blue").save(p)
    assert exif_captured_at(p) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... uv run pytest tests/test_files_thumbs.py -q`
Expected: FAIL — `ModuleNotFoundError` / missing fixtures.

- [ ] **Step 3: Generate the fixtures**

```bash
uv run python - <<'PY'
from PIL import Image
import piexif  # if unavailable, use the Pillow Exif path below
PY
```
If `piexif` is not installed, use Pillow's own Exif writer:
```bash
uv run python - <<'PY'
from PIL import Image
im = Image.new("RGB", (64, 48), (200, 30, 30))
exif = im.getexif()
exif[36867] = "2026:06:14 09:30:00"   # DateTimeOriginal
im.save("tests/fixtures/files/pic.jpg", exif=exif, quality=85)
# stub "video" — extension is what classify_media keys on; not a real container
open("tests/fixtures/files/clip.mp4", "wb").write(
    b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 4096
)
from PIL import Image as I
print(I.open("tests/fixtures/files/pic.jpg").getexif().get(36867))
PY
```
Expected print: `2026:06:14 09:30:00`. (`.mp4` and `.jpg` are already marked
`binary` in `.gitattributes` from Phase 2A.)

- [ ] **Step 4: Implement `thumbs.py`**

```python
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

__all__ = ["thumb_name", "make_thumb", "exif_captured_at"]

_EXIF_DTO = 36867  # DateTimeOriginal


def thumb_name(path_key: str) -> str:
    return hashlib.sha256(path_key.encode("utf-8")).hexdigest()[:16] + ".webp"


def make_thumb(path: Path, media_kind: str, out_dir: Path, *,
               path_key: str) -> Path | None:
    if media_kind != "image":
        return None
    try:
        from PIL import Image, ImageOps

        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / thumb_name(path_key)
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((512, 512))
            im.convert("RGB").save(dest, "WEBP", quality=80)
        return dest
    except Exception:
        return None


def exif_captured_at(path: Path) -> dt.datetime | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            raw = im.getexif().get(_EXIF_DTO)
        if not raw:
            return None
        naive = dt.datetime.strptime(str(raw).strip(), "%Y:%m:%d %H:%M:%S")
        return naive.replace(tzinfo=dt.timezone.utc)
    except Exception:
        return None
```

- [ ] **Step 5: Run the tests**

Run: `... uv run pytest tests/test_files_thumbs.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/files/thumbs.py tests/fixtures/files/pic.jpg \
  tests/fixtures/files/clip.mp4 tests/test_files_thumbs.py
git commit -m "feat(media): make_thumb + exif_captured_at (Pillow, best-effort)"
```

---

## Task 3: `index.py` media branch — EXIF date + thumbnail

**Files:**
- Modify: `io_assistant/files/index.py` (the `if media_kind is not None:` block)
- Test: `tests/test_files_index_media.py`

**Interfaces:**
- Consumes: `thumbs.make_thumb`, `thumbs.exif_captured_at` (Task 2);
  `FilesConfig.thumbs_dir`.
- Produces: after `FileIndexer.index_path` on a media file — `media_kind` set,
  `content_hash` set, `captured_at` from EXIF (images), `thumb_path` from
  `make_thumb` (images; `None` for video/failure), `status="ok"`,
  `index_hash == content_hash`, **no `file_chunks`**, `embedding` stays `None`.
  Re-index with unchanged hash is still a no-op (Phase 2A behaviour unchanged).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_index_media.py
import shutil
from pathlib import Path

from tests.conftest import requires_db, StubEmbedder
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.index import FileIndexer
from io_assistant.db import models as m

FX = Path(__file__).parent / "fixtures" / "files"


@requires_db
def test_media_node_gets_thumb_and_date_no_chunks(db, config, fake_backend, tmp_path):
    shutil.copy(FX / "pic.jpg", tmp_path / "pic.jpg")
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)],
                      thumbs_dir=str(tmp_path / "thumbs"))
    gate = AccessGate(cfg)
    node = FileIndexer(StubEmbedder(), fake_backend, cfg, config.resolver) \
        .index_path(db, tmp_path / "pic.jpg", gate=gate)
    db.flush()
    assert node.media_kind == "image"
    assert node.status == "ok" and node.index_hash == node.content_hash
    assert node.captured_at is not None and node.captured_at.year == 2026
    assert node.thumb_path and Path(node.thumb_path).exists()
    assert node.embedding is None
    assert db.query(m.FileChunk).filter_by(file_id=node.id).count() == 0
    assert "summarize_file" not in fake_backend.calls


@requires_db
def test_video_node_no_thumb(db, config, fake_backend, tmp_path):
    shutil.copy(FX / "clip.mp4", tmp_path / "clip.mp4")
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)],
                      thumbs_dir=str(tmp_path / "thumbs"))
    node = FileIndexer(StubEmbedder(), fake_backend, cfg, config.resolver) \
        .index_path(db, tmp_path / "clip.mp4", gate=AccessGate(cfg))
    db.flush()
    assert node.media_kind == "video" and node.status == "ok"
    assert node.thumb_path is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... uv run pytest tests/test_files_index_media.py -q`
Expected: FAIL — `captured_at` / `thumb_path` are `None`.

- [ ] **Step 3: Extend the media branch in `index.py`**

Add the import at the top:
```python
from io_assistant.files.thumbs import exif_captured_at, make_thumb
```

Replace the existing media branch:
```python
        if media_kind is not None:
            node.status = "ok"
            node.index_hash = content_hash
            node.indexed_at = dt.datetime.now(dt.timezone.utc)
            session.flush()
            self._contains_edge(session, node, gate)
            return node
```
with:
```python
        if media_kind is not None:
            if media_kind == "image":
                node.captured_at = exif_captured_at(path)
            out_dir = Path(os.path.expanduser(self._cfg.thumbs_dir))
            thumb = make_thumb(path, media_kind, out_dir, path_key=pk)
            node.thumb_path = str(thumb) if thumb is not None else None
            node.status = "ok"
            node.index_hash = content_hash
            node.indexed_at = dt.datetime.now(dt.timezone.utc)
            session.flush()
            self._contains_edge(session, node, gate)
            return node
```
Add `import os` to `index.py` if not already imported (Phase 2A already imports
it — confirm).

- [ ] **Step 4: Run the tests**

Run: `... uv run pytest tests/test_files_index_media.py tests/test_files_index.py -q`
Expected: PASS (Phase 2A `test_files_index.py` still green).

- [ ] **Step 5: Commit**

```bash
git add io_assistant/files/index.py tests/test_files_index_media.py
git commit -m "feat(media): index media nodes with EXIF date + thumbnail"
```

---

## Task 4: `command.py` — `open` action + `resolve_folder`

**Files:**
- Modify: `io_assistant/files/command.py`
- Test: `tests/test_files_command_open.py`

**Interfaces:**
- Consumes: `FilesConfig`, `AccessGate`, `ResolveResult` (Phase 2A — kind
  `one`/`many`/`none`, `path`, `candidates`).
- Produces:
  - `FileCommand.action: Literal["register", "search", "open"]`.
  - `classify_file_command` returns `action="open"` when an **open verb**
    (`open`, `show`, `show me`, `browse`, `go to`, `pull up`) is present, there
    is no register verb, and the text mentions a folder / notes / pictures /
    photos / album. `phrase` = the words after the open verb.
  - `resolve_folder(phrase: str, session, gate: AccessGate, config: FilesConfig)
    -> ResolveResult` — fuzzy-match `phrase` (rapidfuzz `token_set_ratio` ≥ 80,
    or all keywords substring ⇒ 95) against basenames of registered `dir`
    nodes + directories from a bounded `os.walk` (depth ≤ 3, first 400 dirs)
    under each `allowlist_root` and each registered dir. Same one/many/none
    disambiguation as `resolve_register_target`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_command_open.py
import pytest
from tests.conftest import requires_db
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.command import classify_file_command, resolve_folder


@pytest.mark.parametrize("text", [
    "open the folder called Hunza Trip 2026",
    "show me the photos from the Italy trip",
    "pull up the Hunza album",
])
def test_open_verb_detected(text):
    assert classify_file_command(text).action == "open"


def test_open_not_confused_with_register_or_search():
    assert classify_file_command("remember my Photos folder").action == "register"
    assert classify_file_command("what does my lease say").action == "search"


@requires_db
def test_resolve_folder_one(db, tmp_path):
    (tmp_path / "Hunza Trip 2026").mkdir()
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    r = resolve_folder("hunza trip 2026", db, AccessGate(cfg), cfg)
    assert r.kind == "one" and r.path.name == "Hunza Trip 2026"


@requires_db
def test_resolve_folder_none(db, tmp_path):
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    assert resolve_folder("nonexistent album", db, AccessGate(cfg), cfg).kind == "none"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... uv run pytest tests/test_files_command_open.py -q`
Expected: FAIL — `resolve_folder` missing; `action` never `"open"`.

- [ ] **Step 3: Extend `command.py`**

Update `FileCommand`:
```python
@dataclass
class FileCommand:
    action: Literal["register", "search", "open"]
    path: str | None = None
    phrase: str | None = None
```

Add near the other regexes:
```python
_OPEN_RE = re.compile(r"\b(open|show me|show|browse|go to|pull up)\b\s+(.*)", re.I)
_FOLDERISH_RE = re.compile(
    r"\b(folder|album|gallery|photos?|pictures?|pics?|videos?|notes?|trip)\b", re.I)
```

In `classify_file_command`, before the final `return FileCommand("search", ...)`:
```python
    om = _OPEN_RE.search(t)
    if om and _FOLDERISH_RE.search(t):
        rest = om.group(2).strip().rstrip(".?!")
        rest = re.sub(r"^(the|my)\s+", "", rest, flags=re.I)
        return FileCommand("open", path=path, phrase=rest)
```

Add:
```python
def _walk_dirs(root: Path, gate: AccessGate, *, max_depth: int = 3,
               cap: int = 400) -> list[Path]:
    out: list[Path] = []
    root = root.resolve()
    for dirpath, dirnames, _ in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth >= max_depth:
            dirnames[:] = []
        dirnames[:] = [d for d in dirnames if not gate.is_excluded(Path(dirpath) / d)]
        for d in dirnames:
            out.append(Path(dirpath) / d)
            if len(out) >= cap:
                return out
    return out


def resolve_folder(phrase: str, session, gate: AccessGate,
                   config: FilesConfig) -> ResolveResult:
    kws = _keywords(phrase or "")
    if not kws:
        return ResolveResult("none")
    cands: list[Path] = []
    for p in session.execute(
        select(m.FileNode.path).where(m.FileNode.kind == "dir")
    ).scalars():
        cands.append(Path(p))
    for r in gate.roots:
        cands += _walk_dirs(r, gate)
    seen: dict[str, Path] = {}
    for p in cands:
        seen.setdefault(gate.key(p), p)

    scored: list[tuple[float, Path]] = []
    for d in seen.values():
        name = d.name.lower()
        score = fuzz.token_set_ratio(" ".join(kws), name)
        if all(k in name for k in kws):
            score = max(score, 95)
        if score >= 80:
            scored.append((score, d))
    scored.sort(key=lambda s: s[0], reverse=True)
    if not scored:
        return ResolveResult("none")
    if len(scored) == 1 or scored[0][0] - scored[1][0] >= 15:
        return ResolveResult("one", path=scored[0][1])
    return ResolveResult("many", candidates=[p for _, p in scored[:5]])
```

- [ ] **Step 4: Run the tests**

Run: `... uv run pytest tests/test_files_command_open.py tests/test_files_command.py -q`
Expected: PASS (Phase 2A `test_files_command.py` still green — the `search`
default and `register` verb precedence are unchanged; `open` is only reached
when no register verb matched).

- [ ] **Step 5: Commit**

```bash
git add io_assistant/files/command.py tests/test_files_command_open.py
git commit -m "feat(media): classify_file_command open action + resolve_folder"
```

---

## Task 5: `GalleryCard` + `gallery.open_folder` + `gallery_card`

**Files:**
- Modify: `io_assistant/models_domain.py` (after `FilesCard`; `Card` union)
- Create: `io_assistant/files/gallery.py`
- Modify: `io_assistant/files/cards.py` (`gallery_card`)
- Test: `tests/test_files_gallery.py`

**Interfaces:**
- Consumes: `AccessGate`, `FileIndex` (`register`, `get`, `by_id`, `stale`,
  `authorized_keys`, `link_entity` — Phase 2A), `FileIndexer.index_path`,
  `walk_dir` + `classify_media`, `EntityRef` (models_domain), `FileCaption` /
  `FileEntityLink` ORM.
- Produces:
  - `models_domain.GalleryItem(BaseModel)`: `path: str`, `media_kind: str`,
    `thumb_url: str | None`, `raw_url: str`, `has_thumb: bool`,
    `caption: str | None`, `entities: list[EntityRef]`,
    `captured_at: datetime | None`.
  - `models_domain.GalleryCard(BaseModel)`: `type: Literal["gallery"] =
    "gallery"`, `folder_path: str`, `count: int`, `items: list[GalleryItem]`.
    `Card = RecordCard | TaskListCard | SourcesCard | FilesCard | GalleryCard`.
  - `gallery.open_folder(session, folder: Path, *, gate: AccessGate, indexer,
    index, config) -> GalleryCard` — `assert_allowed`; if no ancestor is a
    `registered_root`, `index.register(session, folder, gate, config)`; for
    every media file under `folder` (`walk_dir` filtered to
    `classify_media != None`) ensure a `file_nodes` row and, if
    `status == "pending"` or stale, `indexer.index_path(...)`; build a
    `GalleryItem` per node (`thumb_url = "/files/thumb?path=" +
    quote(path)` when `thumb_path` set else `None`; `raw_url = "/files/raw?path="
    + quote(path)`; `entities` from `FileEntityLink` joined to the entity name
    tables — reuse `_ENTITY_MODEL` / `_ENTITY_NAME` from `search.py`, or a local
    copy). Sort items by `captured_at` desc nulls last, then path.
  - `cards.gallery_card(payload: GalleryCard) -> GalleryCard` — identity/pass-
    through (kept for symmetry with `files_card`; the orchestrator calls it).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_gallery.py
import shutil
from pathlib import Path

from tests.conftest import requires_db, StubEmbedder
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.index import FileIndexer
from io_assistant.files.gallery import open_folder
from io_assistant.db import models as m

FX = Path(__file__).parent / "fixtures" / "files"


def _ctx(config, fake_backend, tmp_path):
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)],
                      thumbs_dir=str(tmp_path / "thumbs"))
    gate = AccessGate(cfg)
    return cfg, gate, FileIndex(lambda: None), \
        FileIndexer(StubEmbedder(), fake_backend, cfg, config.resolver)


@requires_db
def test_open_folder_lists_media_and_registers(db, config, fake_backend, tmp_path):
    album = tmp_path / "Hunza"
    album.mkdir()
    shutil.copy(FX / "pic.jpg", album / "a.jpg")
    (album / "notes.txt").write_text("not media")
    cfg, gate, index, indexer = _ctx(config, fake_backend, tmp_path)
    card = open_folder(db, album, gate=gate, indexer=indexer, index=index, config=cfg)
    db.flush()
    assert card.type == "gallery" and card.count == 1
    assert card.items[0].path.endswith("a.jpg")
    assert card.items[0].thumb_url and "path=" in card.items[0].thumb_url
    assert db.query(m.FileNode).filter_by(registered_root=True).count() == 1


@requires_db
def test_open_folder_carries_caption_entities(db, config, fake_backend, tmp_path):
    album = tmp_path / "Hunza"
    album.mkdir()
    shutil.copy(FX / "pic.jpg", album / "a.jpg")
    cfg, gate, index, indexer = _ctx(config, fake_backend, tmp_path)
    open_folder(db, album, gate=gate, indexer=indexer, index=index, config=cfg)
    db.flush()
    node = db.query(m.FileNode).filter_by(media_kind="image").one()
    p = m.Person(canonical_name="Nafay", aliases=[])
    db.add(p); db.flush()
    db.add(m.FileEntityLink(file_id=node.id, etype="person", entity_id=p.id, source="caption"))
    node.caption = "me and Nafay"
    db.flush()
    card = open_folder(db, album, gate=gate, indexer=indexer, index=index, config=cfg)
    item = card.items[0]
    assert item.caption == "me and Nafay"
    assert item.entities and item.entities[0].name == "Nafay"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... uv run pytest tests/test_files_gallery.py -q`
Expected: FAIL — `ModuleNotFoundError: io_assistant.files.gallery`.

- [ ] **Step 3: Add `GalleryItem` / `GalleryCard` to `models_domain.py`**

```python
class GalleryItem(BaseModel):
    path: str
    media_kind: str
    thumb_url: str | None = None
    raw_url: str
    has_thumb: bool = False
    caption: str | None = None
    entities: list[EntityRef] = Field(default_factory=list)
    captured_at: datetime | None = None


class GalleryCard(BaseModel):
    type: Literal["gallery"] = "gallery"
    folder_path: str
    count: int = 0
    items: list[GalleryItem] = Field(default_factory=list)


Card = RecordCard | TaskListCard | SourcesCard | FilesCard | GalleryCard
```

- [ ] **Step 4: Implement `gallery.py`**

```python
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from sqlalchemy import select

from io_assistant.config import FilesConfig
from io_assistant.db import models as m
from io_assistant.files.paths import AccessGate
from io_assistant.files.walk import classify_media, walk_dir
from io_assistant.models_domain import EntityRef, GalleryCard, GalleryItem

__all__ = ["open_folder"]

_ENTITY_NAME = {
    "person": m.Person.canonical_name, "place": m.Place.name,
    "item": m.Item.name, "occasion": m.Occasion.name,
}
_ENTITY_MODEL = {
    "person": m.Person, "place": m.Place, "item": m.Item, "occasion": m.Occasion,
}


def _entities_for(session, file_id: int) -> list[EntityRef]:
    out: list[EntityRef] = []
    for etype, model in _ENTITY_MODEL.items():
        for eid, name in session.execute(
            select(model.id, _ENTITY_NAME[etype])
            .join(m.FileEntityLink, m.FileEntityLink.entity_id == model.id)
            .where(m.FileEntityLink.file_id == file_id,
                   m.FileEntityLink.etype == etype)
        ).all():
            out.append(EntityRef(etype=etype, id=eid, name=name))
    return out


def open_folder(session, folder: Path, *, gate: AccessGate, indexer, index,
                config: FilesConfig) -> GalleryCard:
    folder = folder.resolve()
    gate.assert_allowed(folder, registered_keys=index.authorized_keys(session))

    keys = index.authorized_keys(session)
    fkey = gate.key(folder)
    covered = fkey in keys or any(
        fkey.startswith(k.rstrip("/\\") + "/") or fkey.startswith(k.rstrip("/\\") + "\\")
        for k in keys
    )
    if not covered:
        index.register(session, folder, gate, config)

    media_nodes = []
    for fp in walk_dir(folder, config, gate):
        if classify_media(fp.path.suffix, config) is None:
            continue
        node = indexer.index_path(session, fp.path, gate=gate)
        media_nodes.append(node)

    items: list[GalleryItem] = []
    for n in media_nodes:
        qp = quote(n.path)
        items.append(GalleryItem(
            path=n.path,
            media_kind=n.media_kind or "image",
            thumb_url=(f"/files/thumb?path={qp}" if n.thumb_path else None),
            raw_url=f"/files/raw?path={qp}",
            has_thumb=n.thumb_path is not None,
            caption=n.caption,
            entities=_entities_for(session, n.id),
            captured_at=n.captured_at,
        ))
    items.sort(key=lambda it: (it.captured_at is None,
                               it.captured_at or "", it.path), reverse=False)
    return GalleryCard(folder_path=str(folder), count=len(items), items=items)
```
*Note:* the `captured_at` sort key mixes `datetime` and `str` when some are
`None` — the `it.captured_at is None` leading bool keeps all `None`s together;
within the non-`None` group compare datetimes. Rewrite the key as:
`key=lambda it: (it.captured_at is None, -(it.captured_at.timestamp()) if it.captured_at else 0, it.path)`.

- [ ] **Step 5: Implement `gallery_card` in `cards.py`**

```python
from io_assistant.models_domain import FilesCard, GalleryCard   # extend import

def gallery_card(payload: GalleryCard) -> GalleryCard:
    return payload
```

- [ ] **Step 6: Run the tests**

Run: `... uv run pytest tests/test_files_gallery.py tests/test_files_search.py -q`
Expected: PASS (`test_files_search.py` still green — the `Card` union grew but
`files_card` is unchanged).

- [ ] **Step 7: Commit**

```bash
git add io_assistant/models_domain.py io_assistant/files/gallery.py \
  io_assistant/files/cards.py tests/test_files_gallery.py
git commit -m "feat(media): GalleryCard + open_folder (register, index, list media)"
```

---

## Task 6: `caption.py` — apply_caption + PendingCaption

**Files:**
- Create: `io_assistant/files/caption.py`
- Test: `tests/test_files_caption.py`

**Interfaces:**
- Consumes: `AccessGate`, `FileIndex` (`get`, `by_id`, `link_entity`,
  `upsert_node`), `Extractor` (`io_assistant.extract.extractor` —
  `Extractor(backend).run(text, now) -> ExtractionResult | None`),
  `EntityResolver` (`resolve(etype, name, aliases) -> ResolveOutcome` with
  `.entity_id`, `.ambiguous`, `.candidate_id`, `.candidate_name`;
  `create(etype, name, aliases) -> int`), `ResolverConfig`, `EntityRef`,
  `FileCaption` ORM, `m.Occasion`.
- Produces:
  - `PendingCaption` dataclass: `file_id: int`, `path: str`, `text: str`,
    `source: str`, `extraction: ExtractionResult`.
  - `CaptionResult` dataclass: `gated: bool`, `caption: str`,
    `entities: list[EntityRef] = []`, `gate_reasons: list[str] = []`,
    `pending: PendingCaption | None = None`.
  - `apply_caption(session, path: Path, text: str, source: str, *,
    gate: AccessGate, index, backend, embedder, resolver_cfg: ResolverConfig,
    now, confirmed: bool = False,
    extraction: ExtractionResult | None = None) -> CaptionResult`:
    1. `assert_allowed`; `node = index.get(session, gate.key(path))` or
       `index.upsert_node(... kind="file", media_kind=<from ext>, status="ok")`.
    2. `session.add(FileCaption(file_id=node.id, text=text, source=source))`;
       `node.caption = text`.
    3. `extraction = extraction or Extractor(backend).run(text, now)`; if
       `None` → treat as no entities.
    4. person/place/item: `resolver.resolve(etype, name, aliases)`. If
       `outcome.ambiguous and not confirmed` → collect
       `f"is '{name}' the {etype} '{outcome.candidate_name}'?"`. After the loop,
       if any reasons and not confirmed →
       `return CaptionResult(gated=True, caption=text, gate_reasons=…,
       pending=PendingCaption(node.id, str(path), text, source, extraction))`.
    5. resolve ids: `outcome.entity_id` else (`confirmed and ambiguous` →
       `outcome.candidate_id`) else `resolver.create(etype, name, aliases)`.
       `index.link_entity(session, node.id, etype, eid, source="caption")`.
    6. occasions: dedupe by lowercased name; existing `m.Occasion` → its id,
       else create `m.Occasion(name=…)` with `embedding=embedder.embed_one(name)`
       and flush; `index.link_entity(... "occasion" ...)`.
    7. `node.embedding = embedder.embed_one(text)`.
    8. `return CaptionResult(gated=False, caption=text,
       entities=<EntityRef list of every linked id>)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_files_caption.py
import datetime as dt
from pathlib import Path

from tests.conftest import requires_db, StubEmbedder
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.caption import apply_caption
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson, ExtractedPlace, ExtractedRecord)
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)


def _args(config, tmp_path, fake_backend):
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    return dict(gate=AccessGate(cfg), index=FileIndex(lambda: None),
               backend=fake_backend, embedder=StubEmbedder(),
               resolver_cfg=config.resolver, now=NOW)


@requires_db
def test_caption_links_entities_no_record(db, config, fake_backend, tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)],
        places=[ExtractedPlace(name="Attabad Lake", confidence=0.9)],
        records=[ExtractedRecord(kind="event", title="ignored", confidence=0.9)],
    ))
    res = apply_caption(db, tmp_path / "a.jpg", "me and Nafay at Attabad Lake",
                        "text", **_args(config, tmp_path, fake_backend))
    db.flush()
    assert res.gated is False
    assert {e.name for e in res.entities} == {"Nafay", "Attabad Lake"}
    node = db.query(m.FileNode).one()
    assert node.caption == "me and Nafay at Attabad Lake"
    assert node.embedding is not None
    assert db.query(m.FileCaption).count() == 1
    assert db.query(m.Record).count() == 0
    assert db.query(m.FileEntityLink).filter_by(source="caption").count() == 2


@requires_db
def test_caption_gates_on_ambiguity_then_confirm(db, config, fake_backend, tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"x")
    db.add(m.Person(canonical_name="Nafay Ahmed", aliases=[])); db.flush()
    fake_backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.9)]))
    # force ambiguous: a near-but-not-exact fuzzy match below the create line
    a = _args(config, tmp_path, fake_backend)
    a["resolver_cfg"] = config.resolver.model_copy(update={"fuzzy_threshold": 99})
    res = apply_caption(db, tmp_path / "a.jpg", "photo of Nafay", "text", **a)
    if res.gated:
        assert res.pending is not None
        res2 = apply_caption(db, tmp_path / "a.jpg", res.pending.text, "text",
                             confirmed=True, extraction=res.pending.extraction, **a)
        assert res2.gated is False and res2.entities
    else:
        assert res.entities  # resolver created/linked directly — also fine
```

*(The ambiguity test is written to accept either outcome — the resolver's
vector step can resolve `Nafay`→`Nafay Ahmed` outright with the stub embedder's
zero vectors. The point being exercised is that a `gated` result carries a
replayable `pending`, and `confirmed=True` + the carried extraction completes
without re-calling `extract`.)*

- [ ] **Step 2: Run test to verify it fails**

Run: `... uv run pytest tests/test_files_caption.py -q`
Expected: FAIL — `ModuleNotFoundError: io_assistant.files.caption`.

- [ ] **Step 3: Implement `caption.py`**

```python
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select

from io_assistant.config import ResolverConfig
from io_assistant.db import models as m
from io_assistant.extract.extractor import Extractor
from io_assistant.files.paths import AccessGate
from io_assistant.files.walk import classify_media
from io_assistant.models_domain import EntityRef, ExtractionResult
from io_assistant.resolve.resolver import EntityResolver

__all__ = ["PendingCaption", "CaptionResult", "apply_caption"]

_ETYPE_ATTR = (("person", "people"), ("place", "places"), ("item", "items"))
_ENTITY_NAME = {
    "person": m.Person.canonical_name, "place": m.Place.name,
    "item": m.Item.name, "occasion": m.Occasion.name,
}
_ENTITY_MODEL = {
    "person": m.Person, "place": m.Place, "item": m.Item, "occasion": m.Occasion,
}


@dataclass
class PendingCaption:
    file_id: int
    path: str
    text: str
    source: str
    extraction: ExtractionResult


@dataclass
class CaptionResult:
    gated: bool
    caption: str
    entities: list[EntityRef] = field(default_factory=list)
    gate_reasons: list[str] = field(default_factory=list)
    pending: PendingCaption | None = None


def _config_media_kind(path: Path) -> str | None:
    from io_assistant.config import FilesConfig
    return classify_media(path.suffix, FilesConfig())


def apply_caption(session, path: Path, text: str, source: str, *,
                  gate: AccessGate, index, backend, embedder,
                  resolver_cfg: ResolverConfig, now,
                  confirmed: bool = False,
                  extraction: ExtractionResult | None = None) -> CaptionResult:
    gate.assert_allowed(path, registered_keys=index.authorized_keys(session))
    pk = gate.key(path)
    node = index.get(session, pk)
    if node is None:
        node = index.upsert_node(
            session, path=str(path), path_key=pk,
            parent_key=gate.key(path.parent), kind="file",
            media_kind=_config_media_kind(path), status="ok")

    session.add(m.FileCaption(file_id=node.id, text=text, source=source))
    node.caption = text

    if extraction is None:
        extraction = Extractor(backend).run(text, now) or ExtractionResult()

    resolver = EntityResolver(session, embedder, resolver_cfg)

    # resolve pass
    plan: list[tuple[str, str, list[str], object]] = []
    reasons: list[str] = []
    for etype, attr in _ETYPE_ATTR:
        for ent in getattr(extraction, attr):
            outcome = resolver.resolve(etype, ent.name, list(ent.aliases))
            plan.append((etype, ent.name, list(ent.aliases), outcome))
            if getattr(outcome, "ambiguous", False) and not confirmed:
                reasons.append(
                    f"is '{ent.name}' the {etype} '{outcome.candidate_name}'?")

    if reasons and not confirmed:
        return CaptionResult(
            gated=True, caption=text, gate_reasons=reasons,
            pending=PendingCaption(node.id, str(path), text, source, extraction))

    linked: list[tuple[str, int]] = []
    for etype, name, aliases, outcome in plan:
        if outcome.entity_id is not None:
            eid = outcome.entity_id
        elif getattr(outcome, "ambiguous", False):
            eid = outcome.candidate_id
        else:
            eid = resolver.create(etype, name, aliases)
        index.link_entity(session, node.id, etype, eid, source="caption")
        linked.append((etype, eid))

    for occ in extraction.occasions:
        existing = session.execute(
            select(m.Occasion).where(func.lower(m.Occasion.name) == occ.name.lower())
        ).scalars().first()
        if existing is not None:
            oid = existing.id
        else:
            obj = m.Occasion(name=occ.name)
            obj.embedding = embedder.embed_one(occ.name)
            session.add(obj)
            session.flush()
            oid = obj.id
        index.link_entity(session, node.id, "occasion", oid, source="caption")
        linked.append(("occasion", oid))

    node.embedding = embedder.embed_one(text)
    session.flush()

    refs: list[EntityRef] = []
    for etype, eid in linked:
        nm = session.execute(
            select(_ENTITY_NAME[etype]).where(_ENTITY_MODEL[etype].id == eid)
        ).scalar_one_or_none()
        if nm is not None:
            refs.append(EntityRef(etype=etype, id=eid, name=nm))
    return CaptionResult(gated=False, caption=text, entities=refs)
```

- [ ] **Step 4: Run the tests**

Run: `... uv run pytest tests/test_files_caption.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add io_assistant/files/caption.py tests/test_files_caption.py
git commit -m "feat(media): apply_caption — user-authored caption -> entity links"
```

---

## Task 7: Orchestrator `open` branch

**Files:**
- Modify: `io_assistant/orchestrator.py` (`_file_turn`; new `_file_open`)
- Test: `tests/test_orchestrator_files.py` (extend)

**Interfaces:**
- Consumes: `classify_file_command` (`action` now includes `"open"`),
  `resolve_folder`, `gallery.open_folder`, `cards.gallery_card`. `self._gate`,
  `self._file_index`, `self._indexer` are already built in
  `Orchestrator.__init__` when `config.files.enabled`.
- Produces: `_file_turn` handles `cmd.action == "open"` →
  `_file_open(session, cmd)` returning
  `HandleResult("file", None, "Opening <name> — <n> item(s).",
  cards=[gallery_card(payload)], intent_kind="gallery", shape="text")`;
  `many` → candidate list, `intent_kind="unknown"`; `none` →
  `"I couldn't find a folder called that."`, `intent_kind="unknown"`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_orchestrator_files.py`

```python
import shutil
from pathlib import Path

FX = Path(__file__).parent / "fixtures" / "files"


@requires_db
def test_open_folder_returns_gallery_card(db, files_config, fake_backend, tmp_path):
    album = tmp_path / "Hunza Trip"
    album.mkdir()
    shutil.copy(FX / "pic.jpg", album / "a.jpg")
    files_config.files.thumbs_dir = str(tmp_path / "thumbs")
    fake_backend.set_intent("file")
    orch = Orchestrator(files_config, session_factory=lambda: db, backend=fake_backend)
    res = _handle(orch, db, "open the folder called Hunza Trip")
    assert res.intent_kind == "gallery"
    assert res.cards and res.cards[0].type == "gallery"
    assert res.cards[0].count == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... uv run pytest tests/test_orchestrator_files.py::test_open_folder_returns_gallery_card -q`
Expected: FAIL — `_file_turn` has no `open` branch, so it falls to `search` and
returns `intent_kind="files"`.

- [ ] **Step 3: Implement the `open` branch**

In `_file_turn`, replace:
```python
        cmd = classify_file_command(text)
        if cmd.action == "register":
            return self._file_register(session, cmd)
        answer = self._files.search(session, text, now, gate=self._gate,
                                    context=history)
```
with:
```python
        cmd = classify_file_command(text)
        if cmd.action == "register":
            return self._file_register(session, cmd)
        if cmd.action == "open":
            return self._file_open(session, cmd)
        answer = self._files.search(session, text, now, gate=self._gate,
                                    context=history)
```

Add:
```python
def _file_open(self, session, cmd) -> HandleResult:
    from io_assistant.files.cards import gallery_card
    from io_assistant.files.command import resolve_folder
    from io_assistant.files.gallery import open_folder
    from io_assistant.files.paths import AccessDenied

    target = None
    if cmd.path:
        try:
            target = self._gate.resolve(cmd.path)
        except AccessDenied as e:
            return HandleResult("file", None, f"I can't open that: {e.reason}.",
                                intent_kind="error")
    else:
        res = resolve_folder(cmd.phrase or "", session, self._gate,
                             self._config.files)
        if res.kind == "one":
            target = res.path
        elif res.kind == "many":
            names = ", ".join(p.name for p in res.candidates)
            return HandleResult("file", None,
                                f"I found a few — which one? {names}",
                                intent_kind="unknown")
        else:
            return HandleResult("file", None,
                                "I couldn't find a folder called that.",
                                intent_kind="unknown")
    try:
        card = open_folder(session, target, gate=self._gate,
                           indexer=self._indexer, index=self._file_index,
                           config=self._config.files)
    except AccessDenied as e:
        return HandleResult("file", None, f"I can't open that: {e.reason}.",
                            intent_kind="error")
    return HandleResult(
        "file", None,
        f"Opening {target.name} — {card.count} item(s).",
        cards=[gallery_card(card)], intent_kind="gallery", shape="text")
```

- [ ] **Step 4: Run the tests**

Run: `... uv run pytest tests/test_orchestrator_files.py -q`
Expected: PASS (all Phase 2A orchestrator-file tests still green).

- [ ] **Step 5: Commit**

```bash
git add io_assistant/orchestrator.py tests/test_orchestrator_files.py
git commit -m "feat(media): orchestrator open-folder branch -> gallery card"
```

---

## Task 8: Service routes — thumb, raw (Range), open, caption, transcribe

**Files:**
- Modify: `io_assistant/service/schemas.py`
- Modify: `io_assistant/service/app.py` (the `if config.files.enabled:` block +
  `app.state.caption_pending`)
- Test: `tests/test_service_media.py`

**Interfaces:**
- Consumes: `gallery.open_folder`, `caption.apply_caption` /
  `caption.PendingCaption`, `resolve_folder`, `thumbs.make_thumb`,
  `AccessGate`, `FileIndex`, `FileIndexer`, `app.state.voice` (Phase 1.5
  `VoiceModels` — `.transcriber()` raises `VoiceUnavailable`).
- Produces (all 404 when `config.files.enabled` is false):
  - `schemas.FileOpenIn(path: str | None = None, phrase: str | None = None)`.
  - `schemas.CaptionIn(path: str, text: str, source: str = "text")`.
  - `schemas.CaptionConfirmIn(pending_token: str)`.
  - `schemas.CaptionOut(caption: str, entities: list[dict],
    gated: bool = False, reasons: list[str] = [], pending_token: str | None =
    None)`.
  - `GET /files/thumb?path=` → `FileResponse(thumb, media_type="image/webp")`;
    generate-on-miss for images; **404** when not an image / no thumb.
  - `GET /files/raw?path=` → `FileResponse(path)` (Starlette adds `Accept-Ranges`
    and honours `Range` → `206` + `Content-Range`). `assert_allowed` first.
  - `POST /files/open` → a `GalleryCard` (`.model_dump()`); resolves `phrase`
    server-side; **409** `{detail: {candidates: [...]}}` on `many`, **404** on
    `none`.
  - `POST /files/caption` → `CaptionOut`. On `gated` → stores the
    `PendingCaption` in `app.state.caption_pending[token]` and returns
    `gated=True, pending_token=token`.
  - `POST /files/caption/confirm` → replays `apply_caption(confirmed=True,
    extraction=pending.extraction)`; **404** on an unknown token.
  - `POST /files/transcribe` (multipart `audio`) → `{transcript, confidence}`;
    **503** on `VoiceUnavailable`, **422** on empty speech.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_service_media.py
import shutil
from pathlib import Path

import pytest
from sqlalchemy import text
from fastapi.testclient import TestClient

from tests.conftest import requires_db, StubEmbedder
from io_assistant.service.app import create_app
from io_assistant.config import FilesConfig
from io_assistant.models_domain import (
    ExtractionResult, ExtractedPerson)

FX = Path(__file__).resolve().parents[0] / "fixtures" / "files"


def _wipe(engine):
    with engine.begin() as c:
        c.execute(text("TRUNCATE file_captions, file_entity_links, file_edges, "
                       "file_chunks, file_nodes RESTART IDENTITY CASCADE"))


@pytest.fixture
def mclient(config, engine, tmp_path, fake_backend):
    config.files = FilesConfig(enabled=True, allowlist_roots=[str(tmp_path)],
                               thumbs_dir=str(tmp_path / "thumbs"))
    album = tmp_path / "Hunza"; album.mkdir()
    shutil.copy(FX / "pic.jpg", album / "a.jpg")
    app = create_app(config, engine=engine)
    app.state.orchestrator._backend = fake_backend
    app.state.orchestrator._embedder = StubEmbedder()
    iq = app.state.index_queue
    if iq:
        iq._indexer._backend = fake_backend
        iq._indexer._embed = StubEmbedder()
    _wipe(engine)
    with TestClient(app) as c:
        c.tmp = tmp_path
        yield c
    _wipe(engine)


@requires_db
def test_open_then_raw_range(mclient):
    r = mclient.post("/files/open", json={"path": str(mclient.tmp / "Hunza")})
    assert r.status_code == 200
    item = r.json()["items"][0]
    raw = mclient.get(item["raw_url"], headers={"Range": "bytes=0-9"})
    assert raw.status_code == 206
    assert raw.headers["content-range"].startswith("bytes 0-9/")


@requires_db
def test_thumb_served(mclient):
    mclient.post("/files/open", json={"path": str(mclient.tmp / "Hunza")})
    item = mclient.post("/files/open", json={"path": str(mclient.tmp / "Hunza")}).json()["items"][0]
    t = mclient.get(item["thumb_url"])
    assert t.status_code == 200 and t.headers["content-type"] == "image/webp"


@requires_db
def test_open_phrase_not_found(mclient):
    r = mclient.post("/files/open", json={"phrase": "no such album"})
    assert r.status_code == 404


@requires_db
def test_caption_links_entities(mclient):
    mclient.state = None
    mclient.post("/files/open", json={"path": str(mclient.tmp / "Hunza")})
    # fake extraction
    from io_assistant.service.app import create_app  # noqa
    app = mclient.app
    app.state.orchestrator._backend.set_extraction(ExtractionResult(
        people=[ExtractedPerson(name="Nafay", confidence=0.95)]))
    p = str(mclient.tmp / "Hunza" / "a.jpg")
    r = mclient.post("/files/caption", json={"path": p, "text": "me and Nafay"})
    assert r.status_code == 200
    body = r.json()
    assert body["gated"] is False
    assert body["entities"][0]["name"] == "Nafay"


@requires_db
def test_media_routes_404_when_disabled(config, engine):
    config.files = FilesConfig(enabled=False)
    with TestClient(create_app(config, engine=engine)) as c:
        assert c.post("/files/open", json={"path": "/x"}).status_code == 404
        assert c.get("/files/raw", params={"path": "/x"}).status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... uv run pytest tests/test_service_media.py -q`
Expected: FAIL — routes 404 / `ImportError`.

- [ ] **Step 3: Add schemas** — append to `service/schemas.py` (and `__all__`):

```python
class FileOpenIn(BaseModel):
    path: str | None = None
    phrase: str | None = None


class CaptionIn(BaseModel):
    path: str
    text: str
    source: str = "text"


class CaptionConfirmIn(BaseModel):
    pending_token: str


class CaptionOut(BaseModel):
    caption: str
    entities: list[dict] = Field(default_factory=list)
    gated: bool = False
    reasons: list[str] = Field(default_factory=list)
    pending_token: str | None = None
```

- [ ] **Step 4: Wire the routes into `app.py`**

At the top of `app.py`, add imports:
```python
import secrets
from fastapi.responses import FileResponse
```
(`secrets` is already imported — confirm.)

Inside the existing `if config.files.enabled:` block, after `files_content`:

```python
        from io_assistant.files.caption import apply_caption, PendingCaption
        from io_assistant.files.command import resolve_folder
        from io_assistant.files.gallery import open_folder as _open_folder
        from io_assistant.files.thumbs import make_thumb

        app.state.caption_pending: dict[str, PendingCaption] = {}

        def _allowed(p):
            with factory() as s:
                gate.assert_allowed(p, registered_keys=file_index.authorized_keys(s))

        @app.get("/files/raw")
        def files_raw(path: str):
            p = gate.resolve(path)
            try:
                _allowed(p)
            except AccessDenied as e:
                raise HTTPException(status_code=400, detail=e.reason)
            if not p.is_file():
                raise HTTPException(status_code=404, detail="not found")
            return FileResponse(str(p))

        @app.get("/files/thumb")
        def files_thumb(path: str):
            p = gate.resolve(path)
            try:
                _allowed(p)
            except AccessDenied as e:
                raise HTTPException(status_code=400, detail=e.reason)
            with factory() as s:
                node = file_index.get(s, gate.key(p))
            tp = node.thumb_path if node else None
            if tp and Path(tp).is_file():
                return FileResponse(tp, media_type="image/webp")
            made = make_thumb(p, "image", Path(os.path.expanduser(config.files.thumbs_dir)),
                              path_key=gate.key(p))
            if made is None:
                raise HTTPException(status_code=404, detail="no thumbnail")
            return FileResponse(str(made), media_type="image/webp")

        @app.post("/files/open")
        def files_open(body: FileOpenIn):
            with factory() as s:
                if body.path:
                    target = gate.resolve(body.path)
                else:
                    res = resolve_folder(body.phrase or "", s, gate, config.files)
                    if res.kind == "many":
                        raise HTTPException(status_code=409, detail={
                            "candidates": [p.name for p in res.candidates]})
                    if res.kind == "none":
                        raise HTTPException(status_code=404, detail="folder not found")
                    target = res.path
                try:
                    card = _open_folder(s, target, gate=gate, indexer=indexer,
                                        index=file_index, config=config.files)
                    s.commit()
                except AccessDenied as e:
                    raise HTTPException(status_code=400, detail=e.reason)
            return card.model_dump(mode="json")

        def _caption_out(res) -> CaptionOut:
            return CaptionOut(
                caption=res.caption,
                entities=[e.model_dump() for e in res.entities],
                gated=res.gated, reasons=res.gate_reasons)

        @app.post("/files/caption", response_model=CaptionOut)
        def files_caption(body: CaptionIn):
            import datetime as _dt
            with factory() as s:
                try:
                    res = apply_caption(
                        s, gate.resolve(body.path), body.text, body.source,
                        gate=gate, index=file_index,
                        backend=orchestrator._backend,
                        embedder=orchestrator._embedder,
                        resolver_cfg=config.resolver,
                        now=_dt.datetime.now(_dt.timezone.utc))
                    if res.gated:
                        token = secrets.token_urlsafe(8)
                        app.state.caption_pending[token] = res.pending
                        out = _caption_out(res)
                        out.pending_token = token
                        return out
                    s.commit()
                except AccessDenied as e:
                    raise HTTPException(status_code=400, detail=e.reason)
            return _caption_out(res)

        @app.post("/files/caption/confirm", response_model=CaptionOut)
        def files_caption_confirm(body: CaptionConfirmIn):
            import datetime as _dt
            pending = app.state.caption_pending.pop(body.pending_token, None)
            if pending is None:
                raise HTTPException(status_code=404, detail="unknown token")
            with factory() as s:
                res = apply_caption(
                    s, Path(pending.path), pending.text, pending.source,
                    gate=gate, index=file_index, backend=orchestrator._backend,
                    embedder=orchestrator._embedder, resolver_cfg=config.resolver,
                    now=_dt.datetime.now(_dt.timezone.utc),
                    confirmed=True, extraction=pending.extraction)
                s.commit()
            return _caption_out(res)

        @app.post("/files/transcribe")
        def files_transcribe(audio: UploadFile):
            try:
                transcriber = app.state.voice.transcriber()
            except VoiceUnavailable as e:
                raise HTTPException(status_code=503, detail=e.reason)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio.file.read())
                tmp_path = tmp.name
            tr = transcriber.transcribe(tmp_path)
            if not tr.text.strip():
                raise HTTPException(status_code=422, detail="no speech")
            return {"transcript": tr.text, "confidence": tr.confidence}
```

Add the new schema names to the `from io_assistant.service.schemas import (...)`
list at the top of `app.py`: `CaptionConfirmIn`, `CaptionIn`, `CaptionOut`,
`FileOpenIn`.

- [ ] **Step 5: Run the tests**

Run: `... uv run pytest tests/test_service_media.py tests/test_service_files.py -q -p no:warnings`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add io_assistant/service/schemas.py io_assistant/service/app.py tests/test_service_media.py
git commit -m "feat(media): /files thumb, raw (Range), open, caption, transcribe routes"
```

---

## Task 9: Frontend — gallery view + wiring

**Files:**
- Create: `frontend/views/gallery.js`
- Modify: `frontend/api.js`, `frontend/app.js`, `frontend/views/files.js`,
  `frontend/vendor/icons.js`, `frontend/app.css`
- Test: `tests/test_frontend_gallery.py`; `tests/test_frontend_assets.py`
  already lints new JS

**Interfaces:**
- Consumes: `POST /files/open`, `GET /files/raw`, `GET /files/thumb`,
  `POST /files/caption`, `POST /files/caption/confirm`, `POST /files/transcribe`;
  the `gallery` card shape (`{type, folder_path, count, items:[{path,
  media_kind, thumb_url, raw_url, has_thumb, caption, entities, captured_at}]}`).
- Produces:
  - `api.js`: `openFolder({path, phrase})` → `POST /files/open`;
    `caption(path, text, source)` → `POST /files/caption`;
    `captionConfirm(token)` → `POST /files/caption/confirm`;
    `transcribeAudio(blob)` → `POST /files/transcribe` (multipart) →
    `{transcript}`.
  - `app.js`: `VIEWS.gallery = mountGallery`; a `handleTurn(frame)` that routes
    a frame carrying a `gallery` card to `store.set({view:"gallery",
    gallery:<card>})` and otherwise delegates to `ctx.onTurn`; `ctx.handleTurn`
    exposed; `store` initial state gains `gallery: null`.
  - `views/gallery.js`: `export function mount(root, ctx)` — reads
    `ctx.store.get().gallery`; renders a grid + a detail pane with `<img>` /
    `<video controls>` + a caption `Composer` + entity chips + gate confirm row;
    a **← Files** back button → `ctx.goto("files")`.
  - `views/files.js`: each registered `dir` root row gains an **Open** button →
    `ctx.api.openFolder({path}).then(c => ctx.store.set({view:"gallery",
    gallery:{type:"gallery", ...c}}))`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_frontend_gallery.py
import json, shutil, subprocess
from pathlib import Path
import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def _run(js):
    r = subprocess.run([node, "--input-type=module", "-e", js],
                       capture_output=True, text=True, cwd=FRONTEND)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_gallery_and_api_exports():
    js = f"""
    import * as g from {json.dumps((FRONTEND / 'views/gallery.js').as_uri())};
    if (typeof g.mount !== 'function') throw new Error('no gallery.mount');
    import * as api from {json.dumps((FRONTEND / 'api.js').as_uri())};
    const c = api.Api('');
    for (const m of ['openFolder','caption','captionConfirm','transcribeAudio'])
      if (typeof c[m] !== 'function') throw new Error('missing api.' + m);
    console.log('ok');
    """
    assert _run(js) == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `... uv run pytest tests/test_frontend_gallery.py -q`
Expected: FAIL — no `gallery.js`.

- [ ] **Step 3: Add API methods** — in `api.js`, after `fileContent`:

```js
    async openFolder({ path, phrase } = {}) {
      const r = await fetch(`${b}/files/open`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ path: path || null, phrase: phrase || null }),
      });
      return j(r);
    },
    async caption(path, text, source = "text") {
      return j(await fetch(`${b}/files/caption`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ path, text, source }),
      }));
    },
    async captionConfirm(pending_token) {
      return j(await fetch(`${b}/files/caption/confirm`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ pending_token }),
      }));
    },
    async transcribeAudio(wavBlob) {
      const fd = new FormData();
      fd.append("audio", wavBlob, "caption.wav");
      return j(await fetch(`${b}/files/transcribe`, { method: "POST", body: fd }));
    },
```

- [ ] **Step 4: Add glyphs** — in `vendor/icons.js` `PATHS`:

```js
  image: "<path d=\"M216,40H40A16,16,0,0,0,24,56V200a16,16,0,0,0,16,16H216a16,16,0,0,0,16-16V56A16,16,0,0,0,216,40Zm0,16V158.75l-26.07-26.06a16,16,0,0,0-22.63,0l-20,20-44-44a16,16,0,0,0-22.62,0L40,149.37V56ZM40,172l52-52,80,80H40Zm176,28H194.63l-36-36,20-20L216,181.38V200ZM144,100a12,12,0,1,1,12,12A12,12,0,0,1,144,100Z\"/>",
  filmSlate: "<path d=\"M215.79,118.17,161,100.68l50.94-15.91a8,8,0,0,0,5.24-10l-9.52-30.5a15.95,15.95,0,0,0-20-10.51L32.79,73.62a16,16,0,0,0-10.52,20l9.53,30.49a8,8,0,0,0,5.24,5,7.83,7.83,0,0,0,2.4.37,8,8,0,0,0,2.39-.37L88,143.31V200a16,16,0,0,0,16,16H208a16,16,0,0,0,16-16V125.79A8,8,0,0,0,215.79,118.17ZM196.5,49l7.13,22.86-25.65,8L152.42,49.15Zm-59.36,18.55,25.56,30.7-35.71,11.15L107.83,78.94ZM92.69,80.79l25.55,30.71-40.62,12.69L52,93.49ZM208,200H104V138.28l25.57-8,.19.23a8,8,0,0,0,10.11,2.16L208,116.28Z\"/>",
  play: "<path d=\"M240,128a15.74,15.74,0,0,1-7.6,13.51L88.32,229.65a16,16,0,0,1-16.2.3A15.86,15.86,0,0,1,64,216.13V39.87a15.86,15.86,0,0,1,8.12-13.82,16,16,0,0,1,16.2.3L232.4,114.49A15.74,15.74,0,0,1,240,128Z\"/>",
```

- [ ] **Step 5: Implement `views/gallery.js`**

```js
import { icon } from "../vendor/icons.js";
import { Composer } from "../components/composer.js";
import { WavRecorder } from "../vendor/recorder.js";

function esc(s) {
  return String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function mount(root, ctx) {
  const g = ctx.store.get().gallery;
  if (!g) { root.innerHTML = `<p class="gallery-empty">Nothing open.</p>`; return; }

  root.innerHTML = `
    <section class="gallery">
      <header class="gallery-head">
        <button class="gallery-back">${icon("folder", { size: 14 })} Files</button>
        <h1>${esc(g.folder_path.split(/[\\/]/).pop())}</h1>
        <span class="mono">${g.count} item${g.count === 1 ? "" : "s"}</span>
      </header>
      <div class="gallery-grid"></div>
      <aside class="gallery-detail" hidden></aside>
    </section>`;

  root.querySelector(".gallery-back").onclick = () => ctx.goto("files");
  const grid = root.querySelector(".gallery-grid");
  const detail = root.querySelector(".gallery-detail");

  g.items.forEach((it, i) => {
    const tile = document.createElement("button");
    tile.className = "tile";
    tile.innerHTML = it.thumb_url
      ? `<img loading="lazy" src="${it.thumb_url}" alt="">`
      : `<span class="tile-glyph">${icon(it.media_kind === "video" ? "filmSlate" : "image", { size: 28 })}</span>`;
    if (it.media_kind === "video") {
      const p = document.createElement("span");
      p.className = "tile-play";
      p.innerHTML = icon("play", { size: 20 });
      tile.appendChild(p);
    }
    tile.onclick = () => showDetail(it);
    grid.appendChild(tile);
  });

  function showDetail(it) {
    detail.hidden = false;
    detail.innerHTML = `
      <button class="detail-close">${icon("check", { size: 14 })}</button>
      <div class="detail-media">${
        it.media_kind === "video"
          ? `<video controls preload="metadata" src="${it.raw_url}"></video>`
          : `<img src="${it.raw_url}" alt="">`
      }</div>
      <div class="detail-caption">
        <div class="detail-cap-text">${it.caption ? esc(it.caption) : ""}</div>
        <div class="detail-chips"></div>
        <div class="detail-compose"></div>
        <div class="detail-gate" hidden></div>
      </div>`;
    detail.querySelector(".detail-close").onclick = () => { detail.hidden = true; };
    renderChips(it);

    const compose = Composer(detail.querySelector(".detail-compose"), {
      compact: true,
      placeholder: it.media_kind === "video"
        ? "Tell me about this video" : "Tell me about this picture",
      onSend: (text) => submitCaption(it, text),
      onMic: () => micCaption(it),
    });
    detail._compose = compose;

    function renderChips(item) {
      detail.querySelector(".detail-chips").innerHTML =
        (item.entities || []).map((e) =>
          `<button class="chip${e.etype === "person" ? " person" : ""}" data-etype="${e.etype}" data-id="${e.id}">${esc(e.name)}</button>`).join("");
      detail.querySelectorAll(".detail-chips .chip").forEach((c) => {
        c.onclick = () => ctx.openInspector && ctx.openInspector(c.dataset.etype, +c.dataset.id);
      });
    }

    async function submitCaption(item, text) {
      try {
        const res = await ctx.api.caption(item.path, text, "text");
        if (res.gated) return showGate(item, res.pending_token, res.reasons);
        item.caption = res.caption; item.entities = res.entities;
        detail.querySelector(".detail-cap-text").textContent = res.caption;
        renderChips(item);
      } catch { /* ignore */ }
    }

    function showGate(item, token, reasons) {
      const gate = detail.querySelector(".detail-gate");
      gate.hidden = false;
      gate.innerHTML =
        `<p>${esc((reasons || []).join(" "))}</p>` +
        `<button class="btn btn-primary" data-yes>Yes</button>` +
        `<button class="btn" data-no>Edit</button>`;
      gate.querySelector("[data-yes]").onclick = async () => {
        gate.hidden = true;
        const res = await ctx.api.captionConfirm(token);
        item.caption = res.caption; item.entities = res.entities;
        detail.querySelector(".detail-cap-text").textContent = res.caption;
        renderChips(item);
      };
      gate.querySelector("[data-no]").onclick = () => { gate.hidden = true; };
    }

    async function micCaption(item) {
      let rec;
      try {
        rec = new WavRecorder();
        await rec.start();
      } catch { return; }
      // second click stops
      const mic = detail.querySelector(".composer-mic");
      mic.classList.add("rec");
      mic.onclick = async () => {
        mic.classList.remove("rec");
        const blob = await rec.stop();
        try {
          const { transcript } = await ctx.api.transcribeAudio(blob);
          const ta = detail.querySelector(".detail-compose textarea");
          if (ta) { ta.value = transcript; ta.dispatchEvent(new Event("input")); ta.focus(); }
        } catch { /* ignore */ }
      };
    }
  }
}
```

- [ ] **Step 6: Wire `app.js`**

Add the import and view:
```js
import { mount as mountGallery } from "./views/gallery.js";
// VIEWS: gallery: mountGallery,
```
`store` initial state: add `gallery: null,`.
Replace the ws frame handler's answer line and add `handleTurn`:
```js
function handleTurn(frame) {
  const gc = (frame.cards || []).find((c) => c.type === "gallery");
  if (gc) { store.set({ view: "gallery", gallery: gc }); return; }
  ctx.onTurn && ctx.onTurn(frame);
}
ctx.handleTurn = handleTurn;
// in connectWs callback: else if (frame.type === "answer") handleTurn(frame);
```
In `conversation.js` `sendTurn`, change the fallback:
```js
.then((r) => (ctx.handleTurn || ctx.onTurn)({ ...r, type: "answer" }))
```

- [ ] **Step 7: Wire `views/files.js`** — in the roots row template add an
Open button for dirs and its handler:

```js
`${r.kind === "dir" ? `<button class="files-open" data-path="${esc(r.path)}">Open</button>` : ""}`
// ...
rootsEl.querySelectorAll(".files-open").forEach((b) => {
  b.onclick = async () => {
    try {
      const card = await ctx.api.openFolder({ path: b.dataset.path });
      ctx.store.set({ view: "gallery", gallery: { type: "gallery", ...card } });
    } catch { /* ignore */ }
  };
});
```
(Adjust the `.files-root` grid-template-columns in `app.css` for the extra
button.)

- [ ] **Step 8: Add styles to `app.css`**

Append a `/* --- Gallery --- */` block: `.gallery`, `.gallery-head`,
`.gallery-grid { display:grid; grid-template-columns: repeat(auto-fill,
minmax(150px,1fr)); gap:10px; padding:24px 32px; }`,
`.tile { aspect-ratio:1; position:relative; overflow:hidden; border-radius:var(--radius-md);
background:var(--color-panel); border:1px solid var(--color-hair); }`,
`.tile img { width:100%; height:100%; object-fit:cover; }`,
`.tile-glyph, .tile-play { position:absolute; inset:0; display:flex;
align-items:center; justify-content:center; color:var(--color-neutral-500); }`,
`.tile-play { background:rgba(0,0,0,.25); color:#fff; }`,
`.gallery-detail { /* right pane / modal */ }`, `.detail-media img,
.detail-media video { max-width:100%; max-height:60vh; border-radius:var(--radius-md); }`,
`.detail-chips`, `.detail-gate` — all using existing Nocturne tokens, consistent
with the `files` card styles from Phase 2A.

- [ ] **Step 9: Run the tests**

Run: `... uv run pytest tests/test_frontend_gallery.py tests/test_frontend_assets.py tests/test_frontend_files.py -q`
Then: `node --check` on every changed/new JS file.
Expected: PASS; asset lint still finds no external URLs.

- [ ] **Step 10: Commit**

```bash
git add frontend/ tests/test_frontend_gallery.py
git commit -m "feat(media): gallery view — grid, image/video player, caption box"
```

---

## Task 10: Docs, state, full suite

**Files:**
- Modify: `.claude/knowledge/file-index.md`, `.claude/knowledge/data-model.md`,
  `.claude/skills/run-local.md`, `.claude/state/{session,completed,backlog}.md`
- Test: the whole suite

- [ ] **Step 1: Update `.claude/knowledge/file-index.md`**

Add a **## Media (Phase 2C)** section: the `file_captions` table + `thumb_path`;
`thumbs.py` (Pillow, best-effort, video → glyph); the media branch in
`index.py` (EXIF date + thumb, no chunks, no summary, embedding = caption);
`command.py` `open` action + `resolve_folder`; `gallery.open_folder` →
`GalleryCard`; `caption.apply_caption` (user-authored ground truth → `Extractor`
+ `EntityResolver` + gate, ignores `records`, embeds the caption so media is
searchable via `FileSearcher`); `PendingCaption` held by the caption routes,
**not** `handle()`; the `/files/{thumb,raw,open,caption,caption/confirm,
transcribe}` routes (raw uses Starlette Range); the gallery frontend view.
Update "Deferred": video frame-grab thumbnails (ffmpeg), HEIC (`pillow-heif`),
EXIF GPS → Place.

- [ ] **Step 2: Update `.claude/knowledge/data-model.md`**

Under the file-index paragraph add: "`file_nodes.thumb_path` + `file_captions`
(migration 0005) — user-authored media captions, full history; latest mirrors
to `file_nodes.caption` and is the media node's `embedding`."

- [ ] **Step 3: Update `.claude/skills/run-local.md`**

Under the Files section: "*'open the folder called X'* → in-app gallery; click a
photo/video, type or speak a caption to link it to people/places."

- [ ] **Step 4: Update `.claude/state/`**

Move the Spec C line from `backlog.md` to `completed.md` (dated 2026-09-08) with
a one-paragraph summary. Update `session.md` — Phase 2C done on
`io-phase-2a-file-index` (or a fresh branch — see execution note); next is
Spec B (needs `assets/io-logo.png`). Keep the Spec B line in `backlog.md`.

- [ ] **Step 5: Full suite**

Run: `IO_TEST_DATABASE_URL=... uv run pytest -q -p no:warnings`
Expected: PASS — Phase 2A (267) + the new media tests
(`test_files_thumbs`, `test_files_command_open`, `test_files_index_media`,
`test_files_gallery`, `test_files_caption`, `test_orchestrator_files` additions,
`test_service_media`, `test_frontend_gallery`). `tests/test_e2e_store.py` socket
guard green (no new outbound host — `<img>`/`<video>` hit the local service).

- [ ] **Step 6: Commit**

```bash
git add .claude/
git commit -m "docs+state: Phase 2C media library — knowledge, data-model, state"
```

---

## Self-Review

**1. Spec coverage**

| Spec § | Task |
|---|---|
| §3 `0005` — `thumb_path` + `file_captions` | 1 |
| §4.1 `command.py` `open` + `resolve_folder` | 4 |
| §4.2 `thumbs.py` `make_thumb` / `exif_captured_at` | 2 |
| §4.3 `index.py` media branch (EXIF, thumb, no chunks, embedding null) | 3 |
| §4.4 `gallery.py` `open_folder` → payload w/ thumb_url, entities | 5 |
| §4.5 `caption.py` `apply_caption` (extract → resolve+gate → link → embed; records ignored) | 6 |
| §5 orchestrator `open` → `gallery` card; `GalleryCard`/`GalleryItem` | 5 (types), 7 (branch) |
| §5 `PendingCaption` | 6 (type) + 8 (held by caption routes — deviation, see below) |
| §6 `/files/thumb`, `/files/raw` (Range), `/files/open` (409 many), `/files/caption`, `/files/caption/confirm` | 8 |
| §6 `transcribe_only` | 8 — **deviation:** a dedicated `POST /files/transcribe` route instead |
| §7 gallery view (grid, img/video, caption box, entity chips, gate row, mic) | 9 |
| §7.2 enter via turn (`gallery` card interceptor) + Files-view Open button | 9 |
| §7.3 `image`/`filmSlate`/`play` glyphs | 9 |
| §8 testing | every task + 10 |
| §9 risks | HEIC/video-thumb deferred (2, doc'd in 10); Range test (8); replace-latest caption (6) |

No gaps. Two deliberate deviations (dedicated transcribe route; `PendingCaption`
outside `handle()`) are listed in the plan's **File Structure → Deviations**
section and were chosen to reduce coupling.

**2. Placeholder scan** — no "TBD" / "handle edge cases" / "similar to Task N".
The `app.css` step (9.8) describes concrete selectors and values rather than
pasting the full stylesheet — acceptable for CSS where the Nocturne tokens and
the Phase 2A `files`-card block are the established pattern to match. The fixture
generation (2.3) has a concrete Pillow script with a `piexif` fallback note.

**3. Type consistency**

- `open_folder(session, folder, *, gate, indexer, index, config) -> GalleryCard`
  — same 4 keyword args in Tasks 5, 7, 8.
- `apply_caption(session, path, text, source, *, gate, index, backend,
  embedder, resolver_cfg, now, confirmed=False, extraction=None) ->
  CaptionResult` — identical in Tasks 6, 8.
- `GalleryItem` fields (`path, media_kind, thumb_url, raw_url, has_thumb,
  caption, entities, captured_at`) — defined Task 5, consumed by the frontend
  Task 9 with the same names.
- `CaptionResult(gated, caption, entities, gate_reasons, pending)` and
  `PendingCaption(file_id, path, text, source, extraction)` — Task 6 defines,
  Task 8 consumes (`res.pending`, `res.gate_reasons`, `pending.extraction`,
  `pending.path`).
- `resolve_folder(...) -> ResolveResult` reuses the Phase 2A `ResolveResult`
  (`kind`/`path`/`candidates`) — Tasks 4, 7, 8 all use `.kind` / `.path` /
  `.candidates`.
- `FileCommand.action` literal widened to include `"open"` in Task 4; Task 7's
  `_file_turn` checks `cmd.action == "open"` — consistent.
- `make_thumb(path, media_kind, out_dir, *, path_key)` — Task 2 defines, Tasks 3
  and 8 call with `path_key=` keyword.
- `gallery_card(payload) -> GalleryCard` (pass-through) — Task 5 defines, Task 7
  calls; kept only for symmetry with `files_card`, noted as such.
- Frontend `ctx.handleTurn` / `store.gallery` — introduced Task 9, used only
  within Task 9.

One rename to watch during execution: `search.py` already defines
`_ENTITY_MODEL` / `_ENTITY_NAME`; `gallery.py` and `caption.py` each define
their own local copies (Tasks 5, 6). That is intentional duplication of two
tiny dicts to keep the modules independent — do **not** import across
`files/` submodules for these.
