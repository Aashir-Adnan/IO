"""Background update checks and the hand-off to scripts/update.ps1.

A running process can't replace its own venv/exe, so applying an update spawns
a detached PowerShell script and the service exits (see the spec)."""
from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from io_assistant.config import Config
from io_assistant.updates.check import UpdateStatus, check, find_repo


class UpdateChecker:
    """Daemon thread, modelled on TrackerPoller: best-effort, never raises."""

    def __init__(self, config: Config, *, repo: Path | None = None):
        self._cfg = config.updates
        self.repo = repo or find_repo(config)
        self.status = UpdateStatus()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check_now(self) -> UpdateStatus:
        if self.repo is None:
            self.status = UpdateStatus(error="no git checkout found")
        else:
            self.status = check(self.repo, self._cfg.remote, self._cfg.branch)
        return self.status

    def start(self) -> None:
        if self._thread is not None or not self._cfg.enabled or self.repo is None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        if self._stop.wait(15.0):   # let startup finish first
            return
        while not self._stop.is_set():
            self.check_now()
            self._stop.wait(max(60.0, self._cfg.interval_h * 3600.0))


def spawn_update(repo: Path, relaunch: str) -> None:
    """Start scripts/update.ps1 detached; the caller then exits the service.
    `relaunch` is "exe" (packaged app) or "dev" (dev.ps1 up)."""
    import os

    script = repo / "scripts" / "update.ps1"
    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Root", str(repo), "-ProcessId", str(os.getpid()), "-Relaunch", relaunch],
        creationflags=flags, close_fds=True,
    )
