from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["store", "query", "unknown"]
AnswerShape = Literal["text", "markdown", "diagram"]
Domain = Literal[
    "social", "job", "home", "health", "finance", "learning", "errand", "other"
]

_DOMAIN_VALUES: set[str] = {
    "social", "job", "home", "health", "finance", "learning", "errand", "other",
}


class Utterance(BaseModel):
    text: str
    source: Literal["voice", "text"]
    captured_at: datetime
    transcription_confidence: float | None = None


class ExtractedPerson(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    confidence: float


class ExtractedPlace(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    confidence: float


class ExtractedItem(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    confidence: float


class ExtractedOccasion(BaseModel):
    name: str
    date_phrase: str | None = None
    confidence: float


class ExtractedRecord(BaseModel):
    kind: str
    domain: str | None = None
    title: str
    body: str | None = None
    when_phrase: str | None = None
    due_phrase: str | None = None
    recurrence_phrase: str | None = None
    status: Literal["open", "done", "dropped"] | None = None
    assigned_by: str | None = None
    people: list[str] = Field(default_factory=list)
    places: list[str] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)
    occasions: list[str] = Field(default_factory=list)
    attributes: dict = Field(default_factory=dict)
    confidence: float


class ExtractionResult(BaseModel):
    people: list[ExtractedPerson] = Field(default_factory=list)
    places: list[ExtractedPlace] = Field(default_factory=list)
    items: list[ExtractedItem] = Field(default_factory=list)
    occasions: list[ExtractedOccasion] = Field(default_factory=list)
    records: list[ExtractedRecord] = Field(default_factory=list)


def normalize_kind(raw: str) -> str:
    s = (raw or "").lower()
    s = re.sub(r"[ \-]", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    s = s[:48]
    s = s.strip("_")
    return s or "note"


def normalize_domain(raw: str | None) -> str | None:
    if not raw:
        return None
    s = raw.lower().strip()
    if not s:
        return None
    if s in _DOMAIN_VALUES:
        return s
    return "other"
