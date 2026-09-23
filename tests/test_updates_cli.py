from typer.testing import CliRunner

import io_assistant.cli as cli
import io_assistant.updates.check as ck
from io_assistant.updates.check import UpdateStatus


def _patch(monkeypatch, config, status):
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(ck, "find_repo", lambda c: "/repo")
    monkeypatch.setattr(ck, "check", lambda repo, remote, branch: status)


def test_update_check_reports_available(config, monkeypatch):
    _patch(monkeypatch, config, UpdateStatus(
        available=True, behind=2, subjects=["fix status", "add widgets"],
        branch="main", sha="abc1234"))
    r = CliRunner().invoke(cli.app, ["update", "--check"])
    assert r.exit_code == 0
    assert "2 new commit" in r.output and "add widgets" in r.output


def test_update_check_reports_up_to_date(config, monkeypatch):
    _patch(monkeypatch, config, UpdateStatus(branch="main", sha="abc1234"))
    r = CliRunner().invoke(cli.app, ["update", "--check"])
    assert r.exit_code == 0 and "up to date" in r.output


def test_update_localize_calls_split_local(config, monkeypatch):
    import io_assistant.updates.localize as lz
    monkeypatch.setattr(cli, "load_config", lambda: config)
    monkeypatch.setattr(ck, "find_repo", lambda c: "/repo")
    monkeypatch.setattr(lz, "split_local", lambda repo: {"backend": {"provider": "x"}})
    r = CliRunner().invoke(cli.app, ["update", "--localize"])
    assert r.exit_code == 0 and "config.local.toml" in r.output
