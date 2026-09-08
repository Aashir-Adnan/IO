from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from io_assistant.config import FilesConfig

__all__ = ["AccessGate", "AccessDenied"]

_WIN = os.name == "nt"


class AccessDenied(Exception):
    def __init__(self, path: str, reason: str):
        super().__init__(f"{reason}: {path}")
        self.path = path
        self.reason = reason


class AccessGate:
    """The single authority every filesystem read passes through. Deny by
    default: with no registered paths and no allowlist roots, nothing is
    readable."""

    def __init__(self, config: FilesConfig):
        self._cfg = config
        self._excludes = list(config.exclude_globs)
        self.roots: list[Path] = []
        for r in config.allowlist_roots:
            p = Path(os.path.expanduser(r)).resolve(strict=False)
            if p.exists():
                self.roots.append(p)

    # --- helpers ---------------------------------------------------------
    def resolve(self, raw: str) -> Path:
        p = Path(os.path.expanduser(raw)).resolve(strict=False)
        probe = p
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        if not probe.exists():
            raise AccessDenied(str(p), "path does not resolve")
        return p

    def key(self, path: Path) -> str:
        s = str(path)
        return s.lower() if _WIN else s

    def _ancestor_keys(self, path: Path) -> set[str]:
        return {self.key(a) for a in path.parents}

    def is_excluded(self, path: Path) -> bool:
        s = path.as_posix()
        s_cmp = s.lower() if _WIN else s
        for pat in self._excludes:
            p = pat.lower() if _WIN else pat
            if fnmatch.fnmatch(s_cmp, p):
                return True
        return False

    def _is_symlink_escape(self, path: Path) -> bool:
        if self._cfg.follow_symlinks:
            return False
        probe = path
        while probe != probe.parent:
            if probe.is_symlink():
                return True
            probe = probe.parent
        return False

    # --- the gate ------------------------------------------------------
    def is_allowed(self, path: Path, *, registered_keys: set[str]) -> bool:
        try:
            self.assert_allowed(path, registered_keys=registered_keys)
            return True
        except AccessDenied:
            return False

    def assert_allowed(self, path: Path, *, registered_keys: set[str]) -> None:
        p = path if path.is_absolute() else path.resolve(strict=False)
        if self.is_excluded(p):
            raise AccessDenied(str(p), "matches an exclude pattern")
        if self._is_symlink_escape(p):
            raise AccessDenied(str(p), "symlink (follow_symlinks is off)")
        pk = self.key(p)
        if pk in registered_keys or (registered_keys & self._ancestor_keys(p)):
            return
        for root in self.roots:
            try:
                p.relative_to(root)
                return
            except ValueError:
                continue
        raise AccessDenied(str(p), "not under a registered path or allowlist root")
