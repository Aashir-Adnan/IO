import datetime as dt

import pytest

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.config import FilesConfig
from io_assistant.files.store import FileIndex
from io_assistant.files.paths import AccessGate
from io_assistant.db import models as m


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
