from __future__ import annotations

import threading
import time

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


def open_window(url: str, title: str = "io") -> None:
    try:
        import webview
    except Exception as e:  # pragma: no cover - platform dependent
        raise RuntimeError(
            "pywebview is not available. Run `io serve` and open "
            f"{url} in a browser instead."
        ) from e
    webview.create_window(title, url, width=980, height=720)
    webview.start()
