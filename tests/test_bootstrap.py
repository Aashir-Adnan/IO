import os

import pytest

from tests.conftest import requires_db
from io_assistant.service.bootstrap import (
    BootstrapError, db_reachable, ensure_database)


@requires_db
def test_db_reachable_true(config):
    config.database_url = os.environ["IO_TEST_DATABASE_URL"]
    assert db_reachable(config) is True


@requires_db
def test_ensure_database_migrates_when_reachable(config, monkeypatch):
    config.database_url = os.environ["IO_TEST_DATABASE_URL"]
    calls = []
    monkeypatch.setattr(
        "io_assistant.service.bootstrap._alembic_upgrade",
        lambda cfg: calls.append("migrate"))
    ensure_database(config, start_container=False)
    assert calls == ["migrate"]


def test_ensure_database_no_docker_raises(config, monkeypatch):
    config.database_url = "postgresql+psycopg://io:io@127.0.0.1:59998/none"
    monkeypatch.setattr(
        "io_assistant.service.bootstrap.db_reachable", lambda *a, **k: False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(BootstrapError) as e:
        ensure_database(config)
    assert "docker" in str(e.value).lower()
