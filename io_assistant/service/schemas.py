from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

__all__ = ["UtteranceIn", "UtteranceOut", "HealthOut"]


class UtteranceIn(BaseModel):
    text: str
    source: Literal["text", "voice"] = "text"
    confirm_token: str | None = None


class UtteranceOut(BaseModel):
    intent: str
    message: str
    pending_token: str | None = None
    stored: bool = False


class HealthOut(BaseModel):
    ok: bool
    database: bool
    backend_provider: str
