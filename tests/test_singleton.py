import sys

import pytest

from io_assistant.service.singleton import acquire_single_instance


@pytest.mark.skipif(sys.platform == "win32", reason="flock path is POSIX")
def test_second_acquire_returns_none_posix(tmp_path, monkeypatch):
    monkeypatch.setattr("io_assistant.service.singleton.LOCK_DIR", tmp_path)
    first = acquire_single_instance("io-test-lock")
    assert first is not None
    assert acquire_single_instance("io-test-lock") is None
    first.release()
    third = acquire_single_instance("io-test-lock")
    assert third is not None
    third.release()


@pytest.mark.skipif(sys.platform != "win32", reason="mutex path is Windows")
def test_second_acquire_returns_none_win():
    first = acquire_single_instance("io-test-lock-win")
    assert first is not None
    assert acquire_single_instance("io-test-lock-win") is None
    first.release()


def test_surface_running_instance_no_service(capsys, config):
    from io_assistant.service.singleton import surface_running_instance

    config.service.port = 59999  # nothing listening
    surface_running_instance(config)
    assert "starting" in capsys.readouterr().out.lower()
