from typer.testing import CliRunner

from io_assistant.cli import app


def test_listen_command_registered():
    assert CliRunner().invoke(app, ["listen", "--help"]).exit_code == 0
