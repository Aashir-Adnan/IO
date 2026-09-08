import datetime as dt
from pathlib import Path

from tests.conftest import requires_db, StubEmbedder
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.search import FileSearcher, FileAnswer
from io_assistant.files.cards import files_card
from io_assistant.models_domain import FileHit
from io_assistant.db import models as m

NOW = dt.datetime(2026, 9, 8, tzinfo=dt.timezone.utc)


def _seed_file(db, tmp_path, name, body, hero="hero"):
    p = tmp_path / name
    p.write_text(body)
    idx = FileIndex(lambda: db)
    node = idx.upsert_node(db, path=str(p), path_key=str(p).lower(),
                           parent_key=str(tmp_path).lower(), kind="file",
                           status="ok", content_hash="h", index_hash="h",
                           title=name, summary=body[:100],
                           mtime=NOW, embedding=[0.0] * 768)
    db.add(m.FileChunk(file_id=node.id, ord=0, text=body,
                       token_estimate=len(body) // 4, embedding=[0.0] * 768))
    db.flush()
    return node


def _searcher(config, fake_backend, cfg=None):
    return FileSearcher(StubEmbedder({"pets": [1.0] + [0.0] * 767}),
                        fake_backend, cfg or FilesConfig(), config.resolver)


@requires_db
def test_search_finds_by_fulltext(db, config, fake_backend, tmp_path):
    _seed_file(db, tmp_path, "lease.md", "Pets are allowed with a deposit here.", hero="pets")
    fake_backend.set_file_answer("Pets are allowed with a deposit. (lease.md)")
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    ans = _searcher(config, fake_backend).search(db, "what about pets", NOW, gate=gate)
    assert "deposit" in ans.text
    assert ans.hits and ans.hits[0].path.endswith("lease.md")


@requires_db
def test_empty_result_is_deterministic_no_model(db, config, fake_backend, tmp_path):
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    ans = _searcher(config, fake_backend).search(db, "nothing here", NOW, gate=gate)
    assert "answer_from_files" not in fake_backend.calls
    assert ans.hits == []


@requires_db
def test_freshness_reindexes_changed_file(db, config, fake_backend, tmp_path):
    node = _seed_file(db, tmp_path, "n.md", "old content about pets", hero="pets")
    (tmp_path / "n.md").write_text("new content about pets and deposits")
    node.content_hash = "STALE"
    db.flush()
    fake_backend.set_file_summary({"summary": "s", "names": [], "references": []})
    fake_backend.set_file_answer("ok (n.md)")
    gate = AccessGate(FilesConfig(allowlist_roots=[str(tmp_path)]))
    _searcher(config, fake_backend).search(db, "pets", NOW, gate=gate)
    db.refresh(node)
    assert node.index_hash == node.content_hash != "STALE"


@requires_db
def test_retrieval_limit_enforced(db, config, fake_backend, tmp_path):
    for i in range(10):
        _seed_file(db, tmp_path, f"f{i}.md", "pets pets pets deposit", hero="pets")
    fake_backend.set_file_answer("many (f0.md)")
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)], retrieval_file_limit=3)
    ans = _searcher(config, fake_backend, cfg).search(db, "pets", NOW, gate=AccessGate(cfg))
    assert len(ans.hits) <= 3
    assert len(fake_backend.last_files) <= 3


def test_files_card_builder():
    c = files_card(FileAnswer("t", "text", [FileHit(path="/x/a.md", title="A", why="w")], 5))
    assert c.type == "files" and c.searched == 5 and c.hits[0].path == "/x/a.md"
