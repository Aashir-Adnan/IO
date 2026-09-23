from pathlib import Path

from fastapi.testclient import TestClient

from io_assistant.service.app import create_app
from io_assistant.updates.check import UpdateStatus


class FakeUpdater:
    def __init__(self, status, repo=Path("/repo")):
        self.status = status
        self.repo = repo
        self.checks = 0

    def check_now(self):
        self.checks += 1
        return self.status


def _client(config, status, repo=Path("/repo")):
    app = create_app(config, orchestrator=object(), engine=object(),
                     conversations=object(), voice=object())
    app.state.updater = FakeUpdater(status, repo)
    spawned, exited = [], []
    app.state.spawn_update = lambda repo, relaunch: spawned.append((repo, relaunch))
    app.state.exit_fn = lambda: exited.append(1)
    return TestClient(app), app, spawned, exited


def test_get_update_disabled(config):
    config.updates.enabled = False
    c, *_ = _client(config, UpdateStatus())
    with c:
        assert c.get("/update").json() == {"enabled": False, "available": False}


def test_get_update_returns_cached_status_and_refresh_rechecks(config):
    st = UpdateStatus(available=True, behind=3, subjects=["a"], branch="main", sha="abc")
    c, app, *_ = _client(config, st)
    with c:
        body = c.get("/update").json()
        assert body["enabled"] and body["available"] and body["behind"] == 3
        assert app.state.updater.checks == 0
        c.get("/update?refresh=1")
        assert app.state.updater.checks == 1


def test_apply_refused_when_nothing_to_apply(config):
    c, _, spawned, exited = _client(config, UpdateStatus(available=False))
    with c:
        r = c.post("/update/apply")
    assert r.status_code == 409 and spawned == [] and exited == []


def test_apply_refused_when_tree_dirty(config):
    c, _, spawned, _ = _client(config, UpdateStatus(available=True, dirty=True))
    with c:
        r = c.post("/update/apply")
    assert r.status_code == 409 and "local changes" in r.json()["detail"]
    assert spawned == []


def test_apply_refused_without_a_repo(config):
    c, _, spawned, _ = _client(config, UpdateStatus(available=True), repo=None)
    with c:
        assert c.post("/update/apply").status_code == 409
    assert spawned == []


def test_apply_spawns_updater_then_exits(config):
    c, _, spawned, exited = _client(config, UpdateStatus(available=True, behind=1))
    with c:
        r = c.post("/update/apply")
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert spawned == [(Path("/repo"), "dev")] and exited == [1]
