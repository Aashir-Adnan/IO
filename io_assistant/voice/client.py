from __future__ import annotations

import httpx

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

    def voice_health(self) -> dict:
        try:
            return self._http.get(f"{self._base}/voice/health", timeout=3).json()
        except Exception as e:
            return {"whisper": False, "piper": False, "voice": "?", "reason": str(e)}

    def send_voice(
        self, wav_bytes: bytes, *, conversation_id: int | None = None, speak: bool = True
    ) -> dict:
        r = self._http.post(
            f"{self._base}/voice",
            files={"audio": ("turn.wav", wav_bytes, "audio/wav")},
            data={
                "speak": "1" if speak else "0",
                **({"conversation_id": str(conversation_id)} if conversation_id else {}),
            },
            timeout=180,
        )
        r.raise_for_status()
        return r.json()
