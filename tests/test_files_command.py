import pytest

from tests.conftest import requires_db
from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.command import classify_file_command, resolve_register_target


@pytest.mark.parametrize("text,action", [
    ("remember my Taxes folder in Documents", "register"),
    ("index C:\\Users\\me\\resume.pdf", "register"),
    ("keep track of the notes in ~/work", "register"),
    ("what does my lease say about pets", "search"),
    ("find the Granjur invoice", "search"),
    ("show me the files about Nafay", "search"),
])
def test_action_classification(text, action):
    assert classify_file_command(text).action == action


def test_explicit_windows_path_extracted():
    c = classify_file_command("index C:\\Users\\me\\resume.pdf")
    assert c.path == "C:\\Users\\me\\resume.pdf"


def test_phrase_when_no_explicit_path():
    c = classify_file_command("remember my Taxes folder in Documents")
    assert c.path is None and "Taxes" in c.phrase


@requires_db
def test_resolve_matches_registered_dir(db, tmp_path):
    d = tmp_path / "Taxes 2025"
    d.mkdir()
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    gate = AccessGate(cfg)
    FileIndex(lambda: db).register(db, d, gate, cfg)
    db.flush()
    r = resolve_register_target("taxes 2025", db, gate, cfg)
    assert r.kind == "one" and r.path == d


@requires_db
def test_resolve_ambiguous(db, tmp_path):
    for name in ("Trip Photos", "Trip Notes"):
        (tmp_path / name).mkdir()
    cfg = FilesConfig(allowlist_roots=[str(tmp_path)])
    r = resolve_register_target("trip", db, AccessGate(cfg), cfg)
    assert r.kind == "many" and len(r.candidates) == 2
