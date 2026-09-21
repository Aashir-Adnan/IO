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

__all__ = ["run_service", "open_window", "error_dialog", "raise_window"]

# The live pywebview window in THIS process (None in a headless `io serve`).
# Set by open_window; read by the /window/raise endpoint so a second launch
# focuses the existing window instead of opening a browser.
_WINDOW = None


# The small always-on-top pending-tasks window (None until opened / after close).
_TASKS_WINDOW = None
_TASKS_SIZE = (340, 520)


class TasksApi:
    """js_api of the tasks window: just a close button (the window is frameless)."""

    def close(self):
        w = _TASKS_WINDOW
        if w is not None:
            try:
                w.destroy()
            except Exception:
                pass


def open_tasks_window(app_url: str) -> bool:
    """Open the compact pending-tasks window, or focus it if it is already open.
    Frameless, always on top, bottom-right of the screen, and - like every IO
    window - not draggable. Route `#tasks` renders only the task list."""
    global _TASKS_WINDOW
    import webview

    if _TASKS_WINDOW is not None:
        try:
            _TASKS_WINDOW.restore()
            _TASKS_WINDOW.show()
            return True
        except Exception:
            _TASKS_WINDOW = None
    w, h = _TASKS_SIZE
    x = y = None
    try:
        scr = webview.screens[0]
        x, y = scr.width - w - 24, scr.height - h - 72      # 72: room for the taskbar
    except Exception:
        pass
    win = webview.create_window(
        "IO tasks", app_url.split("#")[0] + "#tasks", width=w, height=h, x=x, y=y,
        on_top=True, frameless=True, resizable=False, easy_drag=False,
        background_color="#12131b", js_api=TasksApi(),
    )

    def _closed():
        global _TASKS_WINDOW
        _TASKS_WINDOW = None

    try:
        win.events.closed += _closed
    except Exception:
        pass
    _TASKS_WINDOW = win
    return True


def raise_window() -> bool:
    """Bring the desktop window to the foreground. False if this process has
    no window (headless service)."""
    w = _WINDOW
    if w is None:
        return False
    try:
        w.restore()
    except Exception:
        pass
    if os.name == "nt":  # pragma: no cover - Windows GUI
        try:
            import ctypes

            hwnd = int(getattr(getattr(w, "native", None), "Handle", 0) or 0)
            if hwnd:
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, 9)          # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
    return True


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
            "pywebview is not available — the IO desktop window can't open. "
            "Install it with `uv sync` (or `pip install pywebview`)."
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
            return self.is_fullscreen()

        def is_fullscreen(self):
            try:
                return bool(getattr(window, "fullscreen", False))
            except Exception:
                return False

        def effects(self):
            return dict(state)

        def open_tasks(self):
            try:
                return open_tasks_window(url)
            except Exception:
                return False

    geo = _load_geometry()
    kw = dict(
        width=geo.get("width", 1180), height=geo.get("height", 760),
        x=geo.get("x"), y=geo.get("y"),
        min_size=(960, 640),
        fullscreen=fullscreen and not geo,
        frameless=True, easy_drag=False,   # drag only via the topbar's app-region
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

    global _WINDOW
    _WINDOW = window

    def _on_closing():
        global _WINDOW
        _save_geometry(window)
        _WINDOW = None

    window.events.shown += _apply_backdrop
    window.events.closing += _on_closing
    webview.start()
    _WINDOW = None
