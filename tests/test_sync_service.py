import datetime as dt
import threading

from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.service.app import create_app
from io_assistant.sync.manager import SyncManager
from io_assistant.sync.stores import FolderStore

T0 = dt.datetime(2026, 9, 1, 9, 0, tzinfo=dt.timezone.utc)


class FakeAuth:
    """Stands in for io_assistant.sync.auth (the real one opens a browser)."""

    def __init__(self, signed_in=False, fail=None):
        self.token = "tok" if signed_in else None
        self.fail = fail
        self.cleared = 0

    def load(self, client_id, client_secret):
        return object() if self.token else None

    def sign_in(self, client_id, client_secret):
        if self.fail:
            raise RuntimeError(self.fail)
        self.token = "tok"
        return object()

    def clear(self):
        self.token = None
        self.cleared += 1


def mgr(config, sf, tmp_path=None, **kw):
    config.sync.enabled = True
    if tmp_path is not None:
        config.sync.folder = str(tmp_path)
    return SyncManager(config, sf, **kw)


def add_friend(sf, name="Ali"):
    with sf() as s:
        u = m.Utterance(text=name, source="text", captured_at=T0)
        s.add_all([u, m.Person(canonical_name=name, aliases=[])])
        s.commit()


@requires_db
def test_folder_mode_syncs_between_two_managers(devices, config, tmp_path):
    a, b = mgr(config, devices["a"], tmp_path), mgr(config, devices["b"], tmp_path)
    add_friend(devices["a"], "Ali")
    sa = a.sync_now()
    assert sa["error"] is None and sa["last_synced_at"] is not None
    sb = b.sync_now()
    assert sb["error"] is None
    with devices["b"]() as s:
        assert [p.canonical_name for p in s.query(m.Person)] == ["Ali"]
    assert a.status()["device_id"] != b.status()["device_id"]


@requires_db
def test_device_id_is_stable_across_restarts(devices, config, tmp_path):
    first = mgr(config, devices["a"], tmp_path).status()["device_id"]
    assert mgr(config, devices["a"], tmp_path).status()["device_id"] == first


@requires_db
def test_drive_mode_needs_sign_in(devices, config):
    x = mgr(config, devices["a"], auth=FakeAuth(signed_in=False))
    st = x.status()
    assert st["enabled"] and st["mode"] == "drive" and not st["signed_in"]
    assert "sign in" in x.sync_now()["error"].lower()


@requires_db
def test_sign_in_and_out(devices, config):
    fa = FakeAuth()
    x = mgr(config, devices["a"], auth=fa, store_factory=lambda creds: FolderStore("."))
    assert x.sign_in()["ok"]
    x._signin_thread.join(5)
    assert x.status()["signed_in"] and x.status()["error"] is None
    x.sign_out()
    assert not x.status()["signed_in"] and fa.cleared == 1


@requires_db
def test_sign_in_failure_is_reported_not_raised(devices, config):
    x = mgr(config, devices["a"], auth=FakeAuth(fail="user closed the window"))
    x.sign_in()
    x._signin_thread.join(5)
    st = x.status()
    assert not st["signed_in"] and "user closed the window" in st["error"]


@requires_db
def test_a_failing_sync_sets_error_and_does_not_raise(devices, config, tmp_path):
    x = mgr(config, devices["a"], tmp_path)
    x._engine().push = lambda: (_ for _ in ()).throw(OSError("disk full"))
    assert "disk full" in x.sync_now()["error"]


def test_disabled_reports_disabled(config):
    config.sync.enabled = False
    assert SyncManager(config, lambda: None).status()["enabled"] is False


class FakeManager:
    def __init__(self):
        self.calls = []

    def status(self):
        return {"enabled": True, "mode": "drive", "signed_in": True, "syncing": False,
                "last_synced_at": 1.0, "error": None, "device_id": "d"}

    def sync_now(self):
        self.calls.append("now")
        return self.status()

    def sign_in(self):
        self.calls.append("in")
        return {"ok": True}

    def sign_out(self):
        self.calls.append("out")


def test_endpoints(config):
    app = create_app(config, orchestrator=object(), engine=object(),
                     conversations=object(), voice=object())
    app.state.sync = fm = FakeManager()
    with TestClient(app) as c:
        assert c.get("/sync").json()["signed_in"] is True
        assert c.post("/sync/now").json()["last_synced_at"] == 1.0
        assert c.post("/sync/signin").json() == {"ok": True}
        assert c.post("/sync/signout").json() == {"ok": True}
    assert fm.calls == ["now", "in", "out"]
