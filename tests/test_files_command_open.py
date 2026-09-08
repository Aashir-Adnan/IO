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
