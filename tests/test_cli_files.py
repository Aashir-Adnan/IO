import pytest
from typer.testing import CliRunner

from tests.conftest import requires_db
from io_assistant.cli import app

runner = CliRunner()


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
