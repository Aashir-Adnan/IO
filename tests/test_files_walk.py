import pytest
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.walk import walk_dir, RegistrationTooLarge, classify_media


def _setup(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("a")
    (tmp_path / "notes" / "b.txt").write_text("b")
    (tmp_path / "notes" / "pic.jpg").write_bytes(b"\xff\xd8\xff")
    (tmp_path / "notes" / "skip.bin").write_bytes(b"\x00")
    (tmp_path / "notes" / "node_modules").mkdir()
    (tmp_path / "notes" / "node_modules" / "x.js").write_text("x")
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    return cfg, AccessGate(cfg), tmp_path / "notes"


def test_walk_yields_supported_files_only(tmp_path):
    cfg, gate, root = _setup(tmp_path)
    got = {p.path.name for p in walk_dir(root, cfg, gate)}
    assert got == {"a.md", "b.txt", "pic.jpg"}


def test_walk_prunes_excluded_dirs(tmp_path):
    cfg, gate, root = _setup(tmp_path)
    assert all("node_modules" not in str(p.path) for p in walk_dir(root, cfg, gate))


def test_walk_sets_media_kind(tmp_path):
    cfg, gate, root = _setup(tmp_path)
    by_name = {p.path.name: p for p in walk_dir(root, cfg, gate)}
    assert by_name["pic.jpg"].media_kind == "image"
    assert by_name["a.md"].media_kind is None


def test_walk_raises_when_over_cap(tmp_path):
    d = tmp_path / "many"
    d.mkdir()
    for i in range(12):
        (d / f"f{i}.txt").write_text("x")
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)], max_files_per_registration=10)
    with pytest.raises(RegistrationTooLarge):
        list(walk_dir(d, cfg, AccessGate(cfg)))


def test_classify_media():
    cfg = FilesConfig()
    assert classify_media(".mp4", cfg) == "video"
    assert classify_media(".PNG", cfg) == "image"
    assert classify_media(".md", cfg) is None
