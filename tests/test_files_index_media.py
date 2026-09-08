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
