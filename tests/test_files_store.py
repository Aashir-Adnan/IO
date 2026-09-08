from pathlib import Path

from tests.conftest import requires_db
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.db import models as m


def _tree(tmp_path):
    root = tmp_path / "proj"
    (root / "sub").mkdir(parents=True)
    (root / "a.md").write_text("# A\nalpha")
    (root / "sub" / "b.md").write_text("# B\nbeta")
    return root


@requires_db
def test_register_dir_creates_root_and_bare_children(db, tmp_path):
    root = _tree(tmp_path)
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    idx = FileIndex(lambda: db)
    res = idx.register(db, root, AccessGate(cfg), cfg)
    db.flush()
    assert res.discovered == 2
    rootnode = idx.get(db, AccessGate(cfg).key(root))
    assert rootnode.registered_root is True and rootnode.kind == "dir"
    kids = db.query(m.FileNode).filter(m.FileNode.kind == "file").all()
    assert {Path(k.path).name for k in kids} == {"a.md", "b.md"}
    assert all(k.status == "pending" and k.content_hash is None for k in kids)


@requires_db
def test_stale_returns_pending_and_hash_mismatch(db, tmp_path):
    root = _tree(tmp_path)
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    idx = FileIndex(lambda: db)
    idx.register(db, root, AccessGate(cfg), cfg)
    db.flush()
    node = db.query(m.FileNode).filter(m.FileNode.kind == "file").first()
    node.status = "ok"
    node.content_hash = "aaa"
    node.index_hash = "aaa"
    db.flush()
    assert node.id not in {n.id for n in idx.stale(db)}
    node.content_hash = "bbb"
    db.flush()
    assert node.id in {n.id for n in idx.stale(db)}


@requires_db
def test_neighbors_contains_and_shares_entity(db, tmp_path):
    idx = FileIndex(lambda: db)
    a = idx.upsert_node(db, path="/x/a.md", path_key="/x/a.md", parent_key="/x", kind="file")
    b = idx.upsert_node(db, path="/x/b.md", path_key="/x/b.md", parent_key="/x", kind="file")
    d = idx.upsert_node(db, path="/x", path_key="/x", parent_key=None, kind="dir")
    db.flush()
    idx.add_edge(db, d.id, a.id, "contains")
    idx.add_edge(db, d.id, b.id, "contains")
    idx.link_entity(db, a.id, "person", 7)
    idx.link_entity(db, b.id, "person", 7)
    db.flush()
    names = {Path(n.path).name for n in idx.neighbors(db, a.id, ("contains", "shares_entity"))}
    assert "b.md" in names


@requires_db
def test_link_entity_bumps_mentions(db):
    idx = FileIndex(lambda: db)
    a = idx.upsert_node(db, path="/x/a.md", path_key="/x/a.md", parent_key="/x", kind="file")
    db.flush()
    idx.link_entity(db, a.id, "person", 3)
    idx.link_entity(db, a.id, "person", 3)
    db.flush()
    row = db.query(m.FileEntityLink).one()
    assert row.mentions == 2


@requires_db
def test_forget_cascades(db, tmp_path):
    root = _tree(tmp_path)
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    idx = FileIndex(lambda: db)
    idx.register(db, root, AccessGate(cfg), cfg)
    db.flush()
    n = idx.forget(db, AccessGate(cfg).key(root))
    db.flush()
    assert n >= 3
    assert db.query(m.FileNode).count() == 0
