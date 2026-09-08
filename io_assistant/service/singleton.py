from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

from io_assistant.config import Config

__all__ = [
    "SingleInstance", "acquire_single_instance", "surface_running_instance",
    "LOCK_DIR",
]

LOCK_DIR = Path(os.path.expanduser("~/.local/share/io"))
_ERROR_ALREADY_EXISTS = 183


class SingleInstance:
    def __init__(self, *, handle=None, fd=None, path: Path | None = None):
        self._handle = handle
        self._fd = fd
        self._path = path

    def release(self) -> None:
        if self._handle is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
            self._handle = None
        if self._fd is not None:
            import fcntl

            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
            self._fd = None
        if self._path is not None:
            try:
                self._path.unlink()
            except OSError:
                pass
            self._path = None

    def __enter__(self) -> "SingleInstance":
        return self

    def __exit__(self, *exc) -> None:
        self.release()


def acquire_single_instance(name: str = "io-assistant") -> SingleInstance | None:
    if sys.platform == "win32":
        import ctypes

        handle = ctypes.windll.kernel32.CreateMutexW(None, False, f"Global\\{name}")
        if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
            return None
        return SingleInstance(handle=handle)

    import fcntl

    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCK_DIR / f"{name}.lock"
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return SingleInstance(fd=fd, path=path)


def surface_running_instance(config: Config) -> None:
    import httpx

    base = f"http://{config.service.host}:{config.service.port}"
    try:
        ok = bool(httpx.get(f"{base}/health", timeout=2).json().get("ok"))
    except Exception:
        ok = False
    if ok:
        webbrowser.open(f"{base}/app/")
        print("IO is already running — opened it in your browser.")
    else:
        print("IO seems to be starting already.")
