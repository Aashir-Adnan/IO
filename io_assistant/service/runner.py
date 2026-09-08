from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import httpx
import uvicorn

from io_assistant._env import load_env_once
from io_assistant.config import Config
from io_assistant.service.app import create_app

load_env_once()

__all__ = ["run_service", "open_window", "error_dialog"]


def error_dialog(message: str) -> None:
    """Show a fatal-startup message in a small window (or print if pywebview is
    unavailable)."""
    try:
        import webview

        safe = (message or "").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")
        webview.create_window(
            "IO — can't start", html=(
                "<body style='font:15px system-ui;margin:0;padding:32px;"
                "background:#161826;color:#e6e6ea'>"
                "<h2 style='margin:0 0 12px'>IO can't start</h2>"
                f"<p style='color:#b9b9c6;line-height:1.5'>{safe}</p></body>"),
            width=520, height=260)
        webview.start()
    except Exception:
        print(message)


def run_service(config: Config, *, block: bool = True):
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(config),
            host=config.service.host,
            port=config.service.port,
            log_level="warning",
            # a windowed PyInstaller build has no stdout — uvicorn's colourised
            # log formatter calls sys.stdout.isatty() and crashes. Disable its
            # dictConfig-based logging entirely.
            log_config=None,
        )
    )
    if block:
        server.run()
        return None

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://{config.service.host}:{config.service.port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/health", timeout=0.5).json().get("ok"):
                break
        except Exception:
            pass
        time.sleep(0.1)
    return server, thread


def _geometry_path() -> Path:
    return Path(os.path.expanduser("~/.local/share/io")) / "window.json"


def _load_geometry() -> dict:
    try:
        return json.loads(_geometry_path().read_text())
    except Exception:
        return {}


def _save_geometry(window) -> None:
    try:
        p = _geometry_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "width": int(window.width), "height": int(window.height),
            "x": int(window.x), "y": int(window.y),
        }))
    except Exception:
        pass


def open_window(url: str, *, title: str = "IO", fullscreen: bool = True) -> None:
    try:
        import webview
    except Exception as e:  # pragma: no cover - platform dependent
        raise RuntimeError(
            "pywebview is not available. Run `io serve` and open "
            f"{url} in a browser instead."
        ) from e

    state = {"acrylic": False}

    class _Api:
        def pick_folder(self):
            try:
                res = window.create_file_dialog(webview.FOLDER_DIALOG)
            except Exception:
                return None
            if not res:
                return None
            return res[0] if isinstance(res, (list, tuple)) else res

        def minimize(self):
            try:
                window.minimize()
            except Exception:
                pass

        def close(self):
            try:
                window.destroy()
            except Exception:
                pass

        def toggle_fullscreen(self):
            try:
                window.toggle_fullscreen()
            except Exception:
                pass

        def effects(self):
            return dict(state)

    geo = _load_geometry()
    kw = dict(
        width=geo.get("width", 1180), height=geo.get("height", 760),
        x=geo.get("x"), y=geo.get("y"),
        min_size=(960, 640),
        fullscreen=fullscreen and not geo,
        frameless=True, easy_drag=True,
        text_select=True,
        js_api=_Api(),
    )
    try:
        window = webview.create_window(title, url, transparent=True, **kw)
    except Exception:
        window = webview.create_window(
            title, url, background_color="#0E0F17", **kw)

    def _apply_backdrop():  # pragma: no cover - Windows GUI
        """Win11 acrylic behind the (transparent) webview."""
        if os.name != "nt":
            return
        try:
            import ctypes

            native = getattr(window, "native", None)
            hwnd = int(getattr(native, "Handle", 0) or 0)
            if not hwnd:
                return
            dwm = ctypes.windll.dwmapi
            dark = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)  # dark mode
            backdrop = ctypes.c_int(3)  # DWMSBT_TRANSIENTWINDOW (acrylic)
            r = dwm.DwmSetWindowAttribute(
                hwnd, 38, ctypes.byref(backdrop), 4)  # DWMWA_SYSTEMBACKDROP_TYPE
            state["acrylic"] = (r == 0)
        except Exception:
            pass

    window.events.shown += _apply_backdrop
    window.events.closing += lambda: _save_geometry(window)
    webview.start()
