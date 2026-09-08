from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "UtteranceIn",
    "UtteranceOut",
    "TurnResponse",
    "VoiceOut",
    "HealthOut",
    "VoiceHealthOut",
    "MessageOut",
    "ConversationOut",
    "ConversationSummary",
    "NewConversationOut",
    "FileRegisterIn",
    "FileRegisterOut",
    "FilesListOut",
    "FileForgetIn",
    "FileForgetOut",
    "FileReindexIn",
    "FileReindexOut",
    "FileContentOut",
]


class UtteranceIn(BaseModel):
    text: str
    source: Literal["text", "voice"] = "text"
    confirm_token: str | None = None
    conversation_id: int | None = None


class UtteranceOut(BaseModel):
    """Deprecated — the voice CLI client still constructs this until Plan 5
    Task 8 rewrites `io listen` onto POST /voice."""
    intent: str
    message: str
    pending_token: str | None = None
    stored: bool = False


class TurnResponse(BaseModel):
    kind: str                       # answer | ack | gate | unknown | error
    intent: str
    text: str
    shape: str = "text"
    cards: list[dict] = Field(default_factory=list)
    pending_token: str | None = None
    conversation_id: int
    message_id: int
    audio_b64: str | None = None


class VoiceOut(TurnResponse):
    transcript: str = ""
    transcript_confidence: float | None = None


class HealthOut(BaseModel):
    ok: bool
    database: bool
    backend_provider: str


class VoiceHealthOut(BaseModel):
    whisper: bool
    piper: bool
    voice: str
    reason: str | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    text: str
    kind: str | None = None
    intent: str | None = None
    source: str = "text"
    created_at: str


class ConversationOut(BaseModel):
    conversation_id: int
    messages: list[MessageOut]


class ConversationSummary(BaseModel):
    id: int
    title: str | None = None
    last_at: str
    message_count: int


class NewConversationOut(BaseModel):
    conversation_id: int


class FileRegisterIn(BaseModel):
    path: str


class FileRegisterOut(BaseModel):
    root: str
    discovered: int
    skipped: list[str] = Field(default_factory=list)


class FilesListOut(BaseModel):
    enabled: bool
    roots: list[dict] = Field(default_factory=list)


class FileForgetIn(BaseModel):
    path: str


class FileForgetOut(BaseModel):
    forgotten: int


class FileReindexIn(BaseModel):
    path: str | None = None


class FileReindexOut(BaseModel):
    queued: int


class FileContentOut(BaseModel):
    path: str
    title: str | None = None
    text: str
