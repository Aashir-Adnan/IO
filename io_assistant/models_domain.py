from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal["store", "query", "file", "unknown"]
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


# --- the unified "decide" plan --------------------------------------------------
# One turn → one Plan → an ordered list of Steps. Today the split-mode planner
# always emits exactly one step (mirrors route+extract); the combined planner
# (backend.decide) may emit several. See docs/superpowers/specs/
# 2026-09-09-unified-decide-pipeline-design.md.

StepKind = Literal["store", "query", "file", "action", "unknown"]


class Step(BaseModel):
    kind: StepKind
    # kind == "store": the extraction to persist (None → extraction failed)
    extraction: "ExtractionResult | None" = None
    # kind == "query" / "file": the (possibly lightly-rewritten) request text
    question: str | None = None
    # kind == "action": a capability slug from io_assistant.actions.registry
    action: str | None = None
    args: dict = Field(default_factory=dict)


class Plan(BaseModel):
    steps: list[Step] = Field(default_factory=list)
    reply_hint: str | None = None   # optional phrasing seed for the responder


# --- structured cards returned alongside a turn's prose -----------------------

class EntityRef(BaseModel):
    etype: Literal["person", "place", "item", "occasion"]
    id: int
    name: str


class RecordCard(BaseModel):
    type: Literal["record"] = "record"
    record_id: int
    kind: str
    domain: str | None = None
    title: str
    entities: list[EntityRef] = Field(default_factory=list)
    when: datetime | None = None
    due: datetime | None = None
    status: str | None = None


class TaskListItem(BaseModel):
    record_id: int
    title: str
    status: str | None = None
    due: datetime | None = None


class TaskListCard(BaseModel):
    type: Literal["tasklist"] = "tasklist"
    items: list[TaskListItem] = Field(default_factory=list)


class SourcesCard(BaseModel):
    type: Literal["sources"] = "sources"
    record_ids: list[int] = Field(default_factory=list)
    count: int = 0
    labels: list[str] = Field(default_factory=list)


class FileHit(BaseModel):
    path: str
    title: str | None = None
    why: str
    media_kind: str | None = None


class FilesCard(BaseModel):
    type: Literal["files"] = "files"
    hits: list[FileHit] = Field(default_factory=list)
    searched: int = 0


class GalleryItem(BaseModel):
    path: str
    media_kind: str                 # image | video | audio | doc | file
    thumb_url: str | None = None
    raw_url: str
    has_thumb: bool = False
    caption: str | None = None
    entities: list[EntityRef] = Field(default_factory=list)
    captured_at: datetime | None = None
    size_bytes: int | None = None
    indexed: bool = True


class GalleryCard(BaseModel):
    type: Literal["gallery"] = "gallery"
    folder_path: str
    count: int = 0
    items: list[GalleryItem] = Field(default_factory=list)


class WebSource(BaseModel):
    title: str
    url: str


class WebCard(BaseModel):
    type: Literal["web"] = "web"
    tier: str                       # a | c | cache
    kind: str                       # news | fact | instant
    sources: list[WebSource] = Field(default_factory=list)
    cached: bool = False


Card = RecordCard | TaskListCard | SourcesCard | FilesCard | GalleryCard | WebCard


_KIND_ALIASES = {
    "todo": "task", "to_do": "task", "task_reminder": "task",
    "reminder": "task", "reminders": "task",
    "chores": "chore",
}


def normalize_kind(raw: str) -> str:
    s = (raw or "").lower()
    s = re.sub(r"[ \-]", "_", s)
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    s = s[:48]
    s = s.strip("_")
    s = _KIND_ALIASES.get(s, s)
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
