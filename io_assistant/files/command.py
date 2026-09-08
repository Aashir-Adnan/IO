from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz
from sqlalchemy import select

from io_assistant.config import FilesConfig
from io_assistant.db import models as m
from io_assistant.files.paths import AccessGate

__all__ = [
    "FileCommand", "classify_file_command",
    "ResolveResult", "resolve_register_target",
]

_PATH_RE = re.compile(r"([A-Za-z]:\\[^\"\n]+|/[^\"\n]+|~[/\\][^\"\n]+)")
_REGISTER_RE = re.compile(
    r"\b(remember|index|register|watch|keep track of|add\s+(?:the\s+)?[\w .\-/]+\s+to\s+(?:your|my)\s+files)\b",
    re.I,
)
_AFTER_VERB_RE = re.compile(
    r"\b(?:remember|index|register|watch|keep track of)\b\s+(.*)", re.I)
_STOPWORDS = {"the", "my", "a", "folder", "directory", "called", "named",
              "in", "under", "at", "of", "files", "file"}


@dataclass
class FileCommand:
    action: Literal["register", "search"]
    path: str | None = None
    phrase: str | None = None


def classify_file_command(text: str) -> FileCommand:
    t = text.strip()
    path_m = _PATH_RE.search(t)
    path = path_m.group(1).strip().rstrip(".") if path_m else None
    if _REGISTER_RE.search(t):
        phrase = None
        if path is None:
            am = _AFTER_VERB_RE.search(t)
            if am:
                phrase = am.group(1).strip().rstrip(".?!")
        return FileCommand("register", path=path, phrase=phrase)
    return FileCommand("search", path=path)


@dataclass
class ResolveResult:
    kind: Literal["one", "many", "none"]
    path: Path | None = None
    candidates: list[Path] = field(default_factory=list)


def _keywords(phrase: str) -> list[str]:
    return [w for w in re.split(r"[\s/\\]+", phrase.lower()) if w and w not in _STOPWORDS]


def _candidate_dirs(session, gate: AccessGate, config: FilesConfig) -> list[Path]:
    out: list[Path] = []
    for p in session.execute(
        select(m.FileNode.path).where(m.FileNode.kind == "dir")
    ).scalars():
        out.append(Path(p))
    for root in gate.roots:
        try:
            for child in os.scandir(root):
                if child.is_dir(follow_symlinks=config.follow_symlinks) \
                        and not gate.is_excluded(Path(child.path)):
                    out.append(Path(child.path))
        except OSError:
            continue
    seen: dict[str, Path] = {}
    for p in out:
        seen.setdefault(gate.key(p), p)
    return list(seen.values())


def resolve_register_target(phrase: str, session, gate: AccessGate,
                            config: FilesConfig) -> ResolveResult:
    kws = _keywords(phrase or "")
    if not kws:
        return ResolveResult("none")
    scored: list[tuple[float, Path]] = []
    for d in _candidate_dirs(session, gate, config):
        name = d.name.lower()
        score = fuzz.token_set_ratio(" ".join(kws), name)
        if all(k in name for k in kws):
            score = max(score, 95)
        if score >= 80:
            scored.append((score, d))
    scored.sort(key=lambda s: s[0], reverse=True)
    if not scored:
        return ResolveResult("none")
    if len(scored) == 1 or scored[0][0] - scored[1][0] >= 15:
        return ResolveResult("one", path=scored[0][1])
    return ResolveResult("many", candidates=[p for _, p in scored[:5]])
