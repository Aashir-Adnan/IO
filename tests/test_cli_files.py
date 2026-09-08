import pytest
from sqlalchemy import text
from typer.testing import CliRunner

from tests.conftest import requires_db
from io_assistant.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _wipe_file_tables(engine):
    """`io files` commits through its own engine (no rolled-back transaction),
    so clean the file tables around every test here."""
    def wipe():
        with engine.begin() as conn:
            conn.execute(text(
                "TRUNCATE file_entity_links, file_edges, file_chunks, file_nodes "
                "RESTART IDENTITY CASCADE"
            ))
    wipe()
    yield
    wipe()


@requires_db
def test_files_add_and_list(tmp_path, monkeypatch, config, engine):
    (tmp_path / "notes.md").write_text("# N\nhello")
    config.files.enabled = True
    config.files.allowlist_roots = [str(tmp_path)]
    monkeypatch.setattr("io_assistant.cli.load_config", lambda *a, **k: config)
    r = runner.invoke(app, ["files", "add", str(tmp_path), "--no-index"])
    assert r.exit_code == 0 and "1" in r.stdout
    r = runner.invoke(app, ["files", "list"])
    assert r.exit_code == 0 and str(tmp_path) in r.stdout


@requires_db
def test_files_add_disabled_errors(monkeypatch, config):
    config.files.enabled = False
    monkeypatch.setattr("io_assistant.cli.load_config", lambda *a, **k: config)
    r = runner.invoke(app, ["files", "add", "/tmp"])
    assert r.exit_code != 0 or "disabled" in r.stdout.lower()
