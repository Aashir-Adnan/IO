from __future__ import annotations

import httpx

from io_assistant.service.schemas import UtteranceIn, UtteranceOut

__all__ = ["ServiceClient"]


class ServiceClient:
    def __init__(self, base_url: str, *, http=None):
        self._base = base_url.rstrip("/")
        self._http = http or httpx

    def health(self) -> bool:
        try:
            return bool(
                self._http.get(f"{self._base}/health", timeout=2).json().get("ok")
            )
        except Exception:
            return False

    def send(self, u: UtteranceIn) -> UtteranceOut:
        r = self._http.post(
            f"{self._base}/utterance", json=u.model_dump(), timeout=120
        )
        r.raise_for_status()
        return UtteranceOut.model_validate(r.json())
