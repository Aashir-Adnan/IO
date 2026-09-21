"""Owns memory sync for the running service: which store, who is signed in, the
background loop, and the status the UI shows. Never raises out of sync/sign-in;
problems land in `status()["error"]`."""
from __future__ import annotations

import threading
import time
import uuid

from io_assistant.config import Config
from io_assistant.db import models as m
from io_assistant.sync.engine import SyncEngine
from io_assistant.sync.stores import FolderStore

NOT_SIGNED_IN = "Not signed in — sign in with Google in Settings → Account."


class SyncManager:
    def __init__(self, config: Config, session_factory, *, auth=None, store_factory=None):
        self._config = config
        self._cfg = config.sync
        self._sf = session_factory
        self._auth = auth
        self._store_factory = store_factory
        self._creds = None
        self._engine_obj: SyncEngine | None = None
        self._device: str | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._signin_thread: threading.Thread | None = None
        self.syncing = False
        self.signing_in = False
        self.last_synced_at: float | None = None
        self.error: str | None = None

    # -- wiring -----------------------------------------------------------
    @property
    def _a(self):
        if self._auth is None:
            from io_assistant.sync import auth

            self._auth = auth
        return self._auth

    @property
    def mode(self) -> str:
        return "folder" if self._cfg.folder else "drive"

    def _signed_in(self) -> bool:
        if self.mode == "folder":
            return True
        if self._creds is None:
            self._creds = self._a.load(self._cfg.client_id, self._cfg.client_secret)
        return self._creds is not None

    def _device_id(self) -> str:
        if self._device is None:
            with self._sf() as s:
                row = s.get(m.SyncState, "device_id")
                if row is None:
                    row = m.SyncState(key="device_id", value={"v": uuid.uuid4().hex[:12]})
                    s.add(row)
                    s.commit()
                self._device = row.value["v"]
        return self._device

    def _engine(self) -> SyncEngine:
        if self._engine_obj is None:
            if self.mode == "folder":
                store = FolderStore(self._cfg.folder)
            elif self._store_factory is not None:
                store = self._store_factory(self._creds)
            else:
                from io_assistant.sync.gdrive import GoogleDriveStore

                store = GoogleDriveStore(self._a.build_service(self._creds))
            self._engine_obj = SyncEngine(self._sf, store, self._device_id(),
                                          resolver_cfg=self._config.resolver)
        return self._engine_obj

    # -- status / actions -------------------------------------------------
    def status(self) -> dict:
        on = self._cfg.enabled
        return {"enabled": on, "mode": self.mode, "signed_in": on and self._signed_in(),
                "syncing": self.syncing, "signing_in": self.signing_in,
                "last_synced_at": self.last_synced_at, "error": self.error,
                "device_id": self._device_id() if on else None}

    def sync_now(self) -> dict:
        if not self._cfg.enabled:
            return self.status()
        with self._lock:                                # one sync at a time
            if not self._signed_in():
                self.error = NOT_SIGNED_IN
                return self.status()
            self.syncing = True
            try:
                self._engine().sync()
                self.last_synced_at, self.error = time.time(), None
            except Exception as e:  # noqa: BLE001 — network, quota, disk, revoked token
                self.error = str(e) or type(e).__name__
            finally:
                self.syncing = False
        return self.status()

    def sign_in(self) -> dict:
        """Start the browser consent flow in the background; poll status()."""
        if self.signing_in:
            return {"ok": True}
        self.signing_in, self.error = True, None

        def run():
            try:
                self._creds = self._a.sign_in(self._cfg.client_id, self._cfg.client_secret)
                self._engine_obj = None
            except Exception as e:  # noqa: BLE001
                self.error = str(e) or type(e).__name__
            finally:
                self.signing_in = False
            if self._creds is not None:
                self.sync_now()

        self._signin_thread = threading.Thread(target=run, daemon=True)
        self._signin_thread.start()
        return {"ok": True}

    def sign_out(self) -> None:
        self._a.clear()
        self._creds, self._engine_obj, self.error = None, None, None

    # -- background loop --------------------------------------------------
    def poke(self) -> None:
        """A local write happened: sync soon instead of waiting the interval."""
        self._wake.set()

    def start(self) -> None:
        if self._thread is not None or not self._cfg.enabled:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        if self._stop.wait(10.0):                       # let startup finish first
            return
        while not self._stop.is_set():
            if self._signed_in():
                self.sync_now()
            self._wake.wait(max(5.0, self._cfg.interval_s))   # or a poke()
            self._wake.clear()
