import pytest
from typer.testing import CliRunner

from io_assistant.cli import app


def test_serve_command_registered():
    result = CliRunner().invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "service" in result.output.lower()


def test_run_command_registered():
    result = CliRunner().invoke(app, ["run", "--help"])
    assert result.exit_code == 0


def test_run_exits_when_instance_held(monkeypatch, config):
    import io_assistant.cli as cli

    monkeypatch.setattr(cli, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(
        "io_assistant.service.singleton.acquire_single_instance",
        lambda *a, **k: None)
    surfaced = {}
    monkeypatch.setattr(
        "io_assistant.service.singleton.surface_running_instance",
        lambda c: surfaced.setdefault("hit", True))
    started = {}
    monkeypatch.setattr(
        "io_assistant.service.runner.run_service",
        lambda *a, **k: started.setdefault("hit", True))

    with pytest.raises(SystemExit) as e:
        cli.run()
    assert e.value.code == 0
    assert surfaced.get("hit") and not started.get("hit")
