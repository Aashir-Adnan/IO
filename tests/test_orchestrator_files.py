import datetime as dt
import shutil
from pathlib import Path

import pytest

from tests.conftest import requires_db

FX = Path(__file__).parent / "fixtures" / "files"
from io_assistant.orchestrator import Orchestrator
from io_assistant.config import FilesConfig
from io_assistant.files.store import FileIndex
from io_assistant.files.paths import AccessGate
from io_assistant.db import models as m


@pytest.fixture(autouse=True)
def _no_real_embedder(monkeypatch, stub_embedder):
    # hermetic: never reach Ollama or load the built-in model
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: stub_embedder)


@pytest.fixture
def files_config(config, tmp_path):
    config.files = FilesConfig(enabled=True, allowlist_roots=[str(tmp_path)])
    return config


def _handle(orch, db, text):
    return orch._handle_in_session(
        db, text, source="text",
        captured_at=dt.datetime.now(dt.timezone.utc),
        confirmed=False, pending=None,
    )


@requires_db
def test_disabled_files_is_polite(db, config, fake_backend):
    fake_backend.set_intent("file")
    orch = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    res = _handle(orch, db, "what's in my notes")
    assert res.intent == "file" and res.intent_kind == "unknown"
    assert "enable" in res.message.lower()


@requires_db
def test_file_search_returns_files_card(db, files_config, fake_backend, tmp_path):
    (tmp_path / "lease.md").write_text("# Lease\nPets allowed with a deposit.")
    fake_backend.set_intent("file")
    fake_backend.set_file_answer("Pets allowed with a deposit. (lease.md)")
    orch = Orchestrator(files_config, session_factory=lambda: db, backend=fake_backend)
    gate = AccessGate(files_config.files)
    FileIndex(lambda: db).register(db, tmp_path, gate, files_config.files)
    db.flush()
    res = _handle(orch, db, "what about pets")
    assert res.intent_kind == "files"
    assert res.cards and res.cards[0].type == "files"
    assert db.query(m.Utterance).filter_by(resolved_intent="file").count() == 1


@requires_db
def test_file_register_phrase_indexes(db, files_config, fake_backend, tmp_path):
    (tmp_path / "Taxes").mkdir()
    (tmp_path / "Taxes" / "w2.txt").write_text("wages 100k")
    fake_backend.set_intent("file")
    orch = Orchestrator(files_config, session_factory=lambda: db, backend=fake_backend)
    res = _handle(orch, db, "remember my Taxes folder")
    assert res.intent_kind in ("ack", "unknown")
    assert db.query(m.FileNode).filter_by(registered_root=True).count() == 1


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


@requires_db
def test_fetch_pictures_of_people_returns_tagged_gallery(db, files_config, fake_backend, tmp_path):
    files_config.ui.name = "Aashir"
    # two tagged media nodes: one of me+nafay, one of just nafay
    for name, tags in (
        ("both.jpg", [("Nafay", "person"), ("Me", "self"), ("Aashir", "self")]),
        ("solo.jpg", [("Nafay", "person")]),
        ("other.jpg", [("Priya", "person")]),
    ):
        n = m.FileNode(path=str(tmp_path / name), path_key=str(tmp_path / name).lower(),
                       kind="file", media_kind="image", status="ok")
        db.add(n); db.flush()
        for term, kind in tags:
            db.add(m.FileTag(file_id=n.id, term=term, norm=term.lower(),
                             kind=kind, media_kind="image", source="caption"))
    db.flush()
    fake_backend.set_intent("file")
    orch = Orchestrator(files_config, session_factory=lambda: db, backend=fake_backend)
    res = _handle(orch, db, "fetch all pictures of me and nafay")
    assert res.intent_kind == "gallery"
    card = res.cards[0]
    assert card.type == "gallery" and card.count == 2      # both + solo, not other
    assert card.items[0].path.endswith("both.jpg")         # covers both terms -> first
