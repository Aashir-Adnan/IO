from pathlib import Path

import pytest

from tests.conftest import requires_db, StubEmbedder
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.index import FileIndexer
from io_assistant.db import models as m


def _indexer(config, backend):
    return FileIndexer(StubEmbedder(), backend, FilesConfig(), config.resolver)


@requires_db
def test_index_text_file_writes_chunks_and_summary(db, config, fake_backend, tmp_path):
    f = tmp_path / "lease.md"
    f.write_text("# Lease\n\n" + "Pets are allowed with a deposit. " * 40)
    fake_backend.set_file_summary({"summary": "A lease about pets.", "names": [], "references": []})
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    node = _indexer(config, fake_backend).index_path(db, f, gate=gate)
    db.flush()
    assert node.status == "ok"
    assert node.summary == "A lease about pets."
    assert node.index_hash == node.content_hash
    assert db.query(m.FileChunk).filter_by(file_id=node.id).count() >= 1


@requires_db
def test_reindex_same_hash_is_noop(db, config, fake_backend, tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# A\nalpha beta")
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    idxr = _indexer(config, fake_backend)
    idxr.index_path(db, f, gate=gate)
    db.flush()
    fake_backend.calls.clear()
    idxr.index_path(db, f, gate=gate)
    db.flush()
    assert "summarize_file" not in fake_backend.calls


@requires_db
def test_entities_linked_only_on_resolver_hit(db, config, fake_backend, tmp_path):
    db.add(m.Person(canonical_name="Nafay", aliases=[]))
    db.flush()
    f = tmp_path / "trip.md"
    f.write_text("# Trip\nWe went with Nafay and someone else.")
    fake_backend.set_file_summary({"summary": "trip", "names": ["Nafay", "Zzxq"], "references": []})
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    node = _indexer(config, fake_backend).index_path(db, f, gate=gate)
    db.flush()
    links = db.query(m.FileEntityLink).filter_by(file_id=node.id).all()
    assert [(l.etype, l.entity_id) for l in links] == [("person", db.query(m.Person).one().id)]


@requires_db
def test_reference_string_creates_edge(db, config, fake_backend, tmp_path):
    (tmp_path / "bill.pdf").write_bytes(b"%PDF-1.4 fake")
    other = tmp_path / "notes.md"
    other.write_text("# Notes\nsee bill.pdf")
    idx = FileIndex(lambda: db)
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    idx.upsert_node(db, path=str(tmp_path / "bill.pdf"),
                    path_key=gate.key(tmp_path / "bill.pdf"),
                    parent_key=gate.key(tmp_path), kind="file")
    db.flush()
    fake_backend.set_file_summary({"summary": "n", "names": [], "references": ["bill.pdf"]})
    node = _indexer(config, fake_backend).index_path(db, other, gate=gate)
    db.flush()
    assert db.query(m.FileEdge).filter_by(src_id=node.id, rel="references").count() == 1


@requires_db
def test_summary_parse_error_falls_back(db, config, fake_backend, tmp_path):
    from io_assistant.backend.interface import BackendParseError

    class Boom(type(fake_backend)):
        def summarize_file(self, *a, **k):
            raise BackendParseError("bad")

    f = tmp_path / "x.md"
    f.write_text("# X\nsome content here")
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    node = FileIndexer(StubEmbedder(), Boom(), FilesConfig(), config.resolver).index_path(db, f, gate=gate)
    db.flush()
    assert node.status == "ok" and node.summary
