import os
import pytest
from pathlib import Path
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate, AccessDenied


def _gate(tmp_path, **kw):
    return AccessGate(FilesConfig(allowlist_roots=[str(tmp_path / "allowed")], **kw))


def test_allowlist_root_is_allowed(tmp_path):
    (tmp_path / "allowed").mkdir()
    f = tmp_path / "allowed" / "a.md"
    f.write_text("x")
    g = _gate(tmp_path)
    assert g.is_allowed(f, registered_keys=set())


def test_outside_everything_is_denied(tmp_path):
    (tmp_path / "allowed").mkdir()
    f = tmp_path / "elsewhere" / "secret.md"
    g = _gate(tmp_path)
    assert not g.is_allowed(f, registered_keys=set())


def test_registered_ancestor_authorises_descendant(tmp_path):
    root = tmp_path / "proj"
    (root / "sub").mkdir(parents=True)
    f = root / "sub" / "notes.md"
    f.write_text("x")
    g = _gate(tmp_path)
    assert g.is_allowed(f, registered_keys={g.key(root)})


def test_excluded_glob_denied_even_inside_allowlist(tmp_path):
    (tmp_path / "allowed" / "node_modules").mkdir(parents=True)
    f = tmp_path / "allowed" / "node_modules" / "x.js"
    f.write_text("x")
    g = _gate(tmp_path)
    assert not g.is_allowed(f, registered_keys=set())


def test_env_file_denied(tmp_path):
    (tmp_path / "allowed").mkdir()
    f = tmp_path / "allowed" / ".env"
    f.write_text("SECRET=1")
    g = _gate(tmp_path)
    assert not g.is_allowed(f, registered_keys=set())


@pytest.mark.skipif(os.name == "nt", reason="symlink perms on Windows")
def test_symlink_denied_unless_allowed(tmp_path):
    (tmp_path / "allowed").mkdir()
    target = tmp_path / "outside.md"
    target.write_text("x")
    link = tmp_path / "allowed" / "link.md"
    link.symlink_to(target)
    assert not _gate(tmp_path).is_allowed(link, registered_keys=set())
    assert _gate(tmp_path, follow_symlinks=True).is_allowed(link, registered_keys=set())


def test_assert_allowed_raises_with_reason(tmp_path):
    (tmp_path / "allowed").mkdir()
    g = _gate(tmp_path)
    with pytest.raises(AccessDenied):
        g.assert_allowed(tmp_path / "nope" / "x.md", registered_keys=set())
