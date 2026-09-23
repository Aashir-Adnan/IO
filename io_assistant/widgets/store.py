"""The home-screen widget layout, kept in a small local JSON file. Per-device on
purpose (not synced) and not in the browser's localStorage, which pywebview
discards between launches."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_WIDGETS = 24
MAX_SETTINGS_BYTES = 20_000


class WidgetItem(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    type: Literal["todo", "weather", "timezones", "alerts"]
    size: Literal["S", "M", "L"]
    col: int = Field(ge=0, le=3)
    row: int = Field(ge=0, le=500)


class WidgetsDoc(BaseModel):
    layout: list[WidgetItem] = Field(max_length=MAX_WIDGETS)
    settings: dict = Field(default_factory=dict)

    @field_validator("settings")
    @classmethod
    def _small(cls, v: dict) -> dict:
        if len(json.dumps(v)) > MAX_SETTINGS_BYTES:
            raise ValueError("settings too large")
        return v


def default_path() -> Path:
    return Path(os.path.expanduser("~/.local/share/io/widgets.json"))


def load(path: Path) -> dict | None:
    """The saved document, or None if there isn't a usable one yet."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return WidgetsDoc(**doc).model_dump()
    except Exception:  # missing, corrupt, or from an incompatible version
        return None


def save(path: Path, doc: WidgetsDoc) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc.model_dump(), indent=1), encoding="utf-8")
    tmp.replace(path)
