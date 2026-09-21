from __future__ import annotations

from pathlib import Path


class FolderStore:
    """A SyncStore backed by a directory."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    def _p(self, path: str) -> Path:
        return self.root / path

    def put(self, path: str, data: bytes) -> None:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".part")     # never expose a half-written file
        tmp.write_bytes(data)
        tmp.replace(p)

    def get(self, path: str) -> bytes:
        return self._p(path).read_bytes()

    def list(self, prefix: str) -> list[str]:
        if not self.root.exists():
            return []
        out = [p.relative_to(self.root).as_posix() for p in self.root.rglob("*")
               if p.is_file() and not p.name.endswith(".part")]
        return sorted(x for x in out if x.startswith(prefix))

    def delete(self, path: str) -> None:
        self._p(path).unlink(missing_ok=True)
