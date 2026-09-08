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

__all__ = ["run_service", "open_window"]


def run_service(config: Config, *, block: bool = True):
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(config),
            host=config.service.host,
            port=config.service.port,
            log_level="warning",
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

    geo = _load_geometry()
    window = webview.create_window(
        title, url,
        width=geo.get("width", 1180), height=geo.get("height", 760),
        x=geo.get("x"), y=geo.get("y"),
        min_size=(960, 640),
        fullscreen=fullscreen and not geo,
        text_select=True,
    )

    def _menu():  # pragma: no cover - GUI
        try:
            from webview.menu import Menu, MenuAction

            def _new_conv():
                try:
                    httpx.post(url.replace("/app/", "/conversation"), timeout=3)
                except Exception:
                    pass
                window.load_url(url)

            return [
                Menu("File", [MenuAction("New Conversation", _new_conv)]),
                Menu("View", [
                    MenuAction("Reload", lambda: window.load_url(url)),
                    MenuAction("Toggle Fullscreen", window.toggle_fullscreen),
                ]),
            ]
        except Exception:
            return []

    window.events.closing += lambda: _save_geometry(window)
    try:
        webview.start(menu=_menu())
    except TypeError:  # older pywebview without menu kwarg
        webview.start()
