from typer.testing import CliRunner

from io_assistant.cli import app


def test_serve_command_registered():
    result = CliRunner().invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "service" in result.output.lower()


def test_run_command_registered():
    result = CliRunner().invoke(app, ["run", "--help"])
    assert result.exit_code == 0
