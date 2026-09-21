"""Unread important/starred Gmail for the Important widget: sender + subject only.

Read-only (`gmail.readonly`), message *metadata* only (From/Subject/Date via
`format=metadata`), never a body. A separate "Connect Gmail" sign-in with its own
keychain entry, so the Drive sync grant is never widened. The service calls
Google; the browser never does. See rules/local-first.md, case 10."""
from __future__ import annotations

import threading
from email.utils import parseaddr

from io_assistant.config import Config

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_ACCOUNT = "google-gmail-refresh-token"
QUERY = "is:unread (is:important OR is:starred)"


def _sender(raw: str) -> str:
    name, addr = parseaddr(raw or "")
    return name or (addr.split("@")[0] if addr else "Unknown")


class GmailConnector:
    def __init__(self, config: Config, *, auth=None, service_factory=None):
        self._cfg = config.sync              # the same Google OAuth client as sync
        self._auth = auth
        self._service_factory = service_factory
        self._creds = None
        self._thread: threading.Thread | None = None
        self.connecting = False
        self.error: str | None = None

    @property
    def _a(self):
        if self._auth is None:
            from io_assistant.sync import auth

            self._auth = auth
        return self._auth

    def _connected(self) -> bool:
        if self._creds is None:
            self._creds = self._a.load(self._cfg.client_id, self._cfg.client_secret,
                                       scopes=GMAIL_SCOPES, account=GMAIL_ACCOUNT)
        return self._creds is not None

    def status(self) -> dict:
        return {"connected": self._connected(), "connecting": self.connecting,
                "error": self.error}

    def connect(self) -> dict:
        """Browser consent in the background; poll status()."""
        if self.connecting:
            return {"ok": True}
        self.connecting, self.error = True, None

        def run():
            try:
                self._creds = self._a.sign_in(self._cfg.client_id, self._cfg.client_secret,
                                              scopes=GMAIL_SCOPES, account=GMAIL_ACCOUNT)
            except Exception as e:  # noqa: BLE001
                self.error = str(e) or type(e).__name__
            finally:
                self.connecting = False

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return {"ok": True}

    def disconnect(self) -> None:
        self._a.clear(account=GMAIL_ACCOUNT)
        self._creds, self.error = None, None

    def _service(self):
        if self._service_factory is not None:
            return self._service_factory(self._creds)
        from googleapiclient.discovery import build

        return build("gmail", "v1", credentials=self._creds, cache_discovery=False)

    def important(self, n: int = 6) -> dict:
        if not self._connected():
            return {"connected": False, "items": [], "error": None}
        try:
            msgs = self._service().users().messages()
            ids = msgs.list(userId="me", q=QUERY, maxResults=n).execute().get("messages", [])
            items = []
            for ref in ids:
                m = msgs.get(userId="me", id=ref["id"], format="metadata",
                             metadataHeaders=["From", "Subject", "Date"]).execute()
                h = {x["name"].lower(): x["value"] for x in m.get("payload", {}).get("headers", [])}
                items.append({"id": m["id"], "from": _sender(h.get("from", "")),
                              "subject": h.get("subject") or "(no subject)",
                              "when_ms": int(m.get("internalDate", 0))})
            return {"connected": True, "items": items, "error": None}
        except Exception as e:  # noqa: BLE001 — quota, revoked token, network
            return {"connected": True, "items": [], "error": str(e) or type(e).__name__}
