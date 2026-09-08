from __future__ import annotations

import datetime as dt
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from io_assistant.config import FilesConfig
from io_assistant.files.paths import AccessGate

__all__ = ["FoundPath", "RegistrationTooLarge", "walk_dir", "classify_media"]

_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


@dataclass
class FoundPath:
    path: Path
    kind: str
    mime: str | None
    media_kind: str | None
    size: int
    mtime: dt.datetime


class RegistrationTooLarge(Exception):
    def __init__(self, count: int, cap: int):
        super().__init__(
            f"{count} files exceeds max_files_per_registration ({cap})"
        )
        self.count = count
        self.cap = cap


def classify_media(suffix: str, config: FilesConfig) -> str | None:
    s = suffix.lower()
    if s not in {e.lower() for e in config.media_extensions}:
        return None
    return "video" if s in _VIDEO_EXTS else "image"


def walk_dir(root: Path, config: FilesConfig, gate: AccessGate) -> Iterator[FoundPath]:
    exts = {e.lower() for e in (*config.index_extensions, *config.media_extensions)}
    cap = config.max_files_per_registration
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=config.follow_symlinks):
        d = Path(dirpath)
        dirnames[:] = [
            name for name in dirnames
            if not gate.is_excluded(d / name)
            and (config.follow_symlinks or not (d / name).is_symlink())
        ]
        for name in filenames:
            p = d / name
            if p.suffix.lower() not in exts:
                continue
            if gate.is_excluded(p):
                continue
            if not config.follow_symlinks and p.is_symlink():
                continue
            try:
                st = p.stat()
            except OSError:
                continue
            count += 1
            if count > cap:
                raise RegistrationTooLarge(count, cap)
            yield FoundPath(
                path=p,
                kind="file",
                mime=mimetypes.guess_type(p.name)[0],
                media_kind=classify_media(p.suffix, config),
                size=st.st_size,
                mtime=dt.datetime.fromtimestamp(st.st_mtime, tz=dt.timezone.utc),
            )
