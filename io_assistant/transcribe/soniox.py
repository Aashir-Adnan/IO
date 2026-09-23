"""Soniox real-time speech-to-text — server-side token minting only.

IO's server never proxies audio. It exchanges the long-lived ``SONIOX_API_KEY``
for a short-lived token (``POST /v1/auth/temporary-api-key``); the browser then
opens the WebSocket to ``stt-rt.soniox.com`` directly with that token. See
rules/local-first.md — this is a provider-gated, opt-in cloud path.
"""
from __future__ import annotations

import httpx

from io_assistant.config import Config

__all__ = ["mint_temp_key", "SonioxUnavailable", "TOKEN_URL", "WS_URL"]

TOKEN_URL = "https://api.soniox.com/v1/auth/temporary-api-key"
WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"


class SonioxUnavailable(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def mint_temp_key(config: Config, *, ttl_seconds: int = 300) -> dict:
    """Return ``{api_key, expires_at, model, websocket_url}`` for the browser.

    Raises ``SonioxUnavailable`` when the feature is off or the key is missing,
    and ``httpx.HTTPError`` when Soniox rejects the request.
    """
    if config.voice.stt_provider != "soniox":
        raise SonioxUnavailable("voice.stt_provider is not 'soniox'")
    key = config.voice.soniox_api_key
    if not key:
        raise SonioxUnavailable("SONIOX_API_KEY is not set in the environment")

    resp = httpx.post(
        TOKEN_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"usage_type": "transcribe_websocket", "expires_in_seconds": ttl_seconds},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "api_key": data["api_key"],
        "expires_at": data.get("expires_at"),
        "model": config.voice.soniox_model,
        "websocket_url": WS_URL,
    }
