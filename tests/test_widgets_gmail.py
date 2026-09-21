import keyring
from fastapi.testclient import TestClient

from io_assistant.service.app import create_app
from io_assistant.sync import auth
from io_assistant.widgets.gmail import GMAIL_ACCOUNT, GMAIL_SCOPES, GmailConnector


class _Exec:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeMessages:
    def __init__(self, ids, headers_by_id):
        self.ids, self.headers = ids, headers_by_id
        self.list_kwargs = None
        self.get_kwargs = []

    def list(self, **kw):
        self.list_kwargs = kw
        return _Exec(lambda: {"messages": [{"id": i} for i in self.ids]} if self.ids else {})

    def get(self, **kw):
        self.get_kwargs.append(kw)
        h = self.headers[kw["id"]]
        return _Exec(lambda: {"id": kw["id"], "internalDate": "1790000000000",
                              "payload": {"headers": h}})


class FakeGmail:
    def __init__(self, ids=(), headers=None):
        self.msgs = FakeMessages(list(ids), headers or {})

    def users(self):
        outer = self

        class U:
            def messages(self):
                return outer.msgs
        return U()


class FakeAuth:
    def __init__(self, token="tok", fail=None):
        self.token, self.fail = token, fail
        self.calls = []

    def load(self, cid, secret, **kw):
        self.calls.append(("load", kw))
        return object() if self.token else None

    def sign_in(self, cid, secret, **kw):
        self.calls.append(("sign_in", kw))
        if self.fail:
            raise RuntimeError(self.fail)
        self.token = "tok"
        return object()

    def clear(self, **kw):
        self.calls.append(("clear", kw))
        self.token = None


def conn(config, gmail=None, **kw):
    fa = kw.pop("auth", FakeAuth())
    return GmailConnector(config, auth=fa, service_factory=lambda creds: gmail), fa


def test_important_returns_sender_and_subject_only(config):
    g = FakeGmail(["m1", "m2"], {
        "m1": [{"name": "From", "value": "Sana Ahmed <sana@example.com>"},
               {"name": "Subject", "value": "Lease renewal"}],
        "m2": [{"name": "From", "value": "billing@bank.example"}]})
    c, _ = conn(config, g)
    out = c.important(2)
    assert out["error"] is None
    assert out["items"] == [
        {"id": "m1", "from": "Sana Ahmed", "subject": "Lease renewal", "when_ms": 1790000000000},
        {"id": "m2", "from": "billing", "subject": "(no subject)", "when_ms": 1790000000000}]
    assert g.msgs.list_kwargs["q"] == "is:unread (is:important OR is:starred)"
    assert g.msgs.list_kwargs["maxResults"] == 2
    assert all(k["format"] == "metadata" for k in g.msgs.get_kwargs)   # never message bodies


def test_no_unread_mail_is_an_empty_list(config):
    c, _ = conn(config, FakeGmail([]))
    assert c.important() == {"connected": True, "items": [], "error": None}


def test_not_connected_makes_no_gmail_call(config):
    c, _ = conn(config, gmail=None, auth=FakeAuth(token=None))
    assert c.important() == {"connected": False, "items": [], "error": None}


def test_api_failures_are_reported_not_raised(config):
    class Boom:
        def users(self):
            raise OSError("quota")
    c, _ = conn(config, Boom())
    out = c.important()
    assert out["items"] == [] and "quota" in out["error"]


def test_connect_uses_the_gmail_scope_and_its_own_keychain_account(config):
    c, fa = conn(config, FakeGmail(), auth=FakeAuth(token=None))
    assert c.status()["connected"] is False
    c.connect()
    c._thread.join(5)
    assert c.status() == {"connected": True, "connecting": False, "error": None}
    kw = next(k for name, k in fa.calls if name == "sign_in")
    assert kw["scopes"] == GMAIL_SCOPES and kw["account"] == GMAIL_ACCOUNT
    c.disconnect()
    assert c.status()["connected"] is False
    assert ("clear", {"account": GMAIL_ACCOUNT}) in fa.calls


def test_connect_failure_is_reported(config):
    c, _ = conn(config, auth=FakeAuth(token=None, fail="window closed"))
    c.connect()
    c._thread.join(5)
    assert "window closed" in c.status()["error"] and not c.status()["connected"]


def test_auth_functions_take_scopes_and_account(monkeypatch):
    seen = {}
    monkeypatch.setattr(keyring, "get_password", lambda svc, user: seen.setdefault("user", user) and "rt")
    creds = auth.load("cid", "sec", scopes=GMAIL_SCOPES, account="acct-x")
    assert seen["user"] == "acct-x"
    assert creds.scopes == GMAIL_SCOPES and creds.refresh_token == "rt"
    assert auth.SCOPES != GMAIL_SCOPES                      # sync stays Drive-only


def test_endpoints(config):
    app = create_app(config, orchestrator=object(), engine=object(),
                     conversations=object(), voice=object())
    c, _ = conn(config, FakeGmail(["m1"], {"m1": [{"name": "From", "value": "A <a@b.c>"},
                                                   {"name": "Subject", "value": "Hi"}]}))
    app.state.gmail = c
    with TestClient(app) as tc:
        assert tc.get("/gmail").json()["connected"] is True
        assert tc.get("/gmail/important").json()["items"][0]["subject"] == "Hi"
        assert tc.post("/gmail/disconnect").json() == {"ok": True}
        assert tc.get("/gmail").json()["connected"] is False
