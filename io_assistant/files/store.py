from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, or_, select

from io_assistant.config import FilesConfig
from io_assistant.db import models as m
from io_assistant.files.paths import AccessDenied, AccessGate
from io_assistant.files.walk import walk_dir

__all__ = ["FileIndex", "RegisterResult"]


@dataclass
class RegisterResult:
    root_id: int
    discovered: int
    skipped: list[str] = field(default_factory=list)


def _parent_key(gate: AccessGate, path: Path) -> str | None:
    parent = path.parent
    return None if parent == path else gate.key(parent)


class FileIndex:
    def __init__(self, session_factory):
        self._sf = session_factory

    # --- reads ----------------------------------------------------------
    def authorized_keys(self, session) -> set[str]:
        return set(session.execute(
            select(m.FileNode.path_key).where(m.FileNode.registered_root)
        ).scalars())

    def get(self, session, path_key: str) -> m.FileNode | None:
        return session.execute(
            select(m.FileNode).where(m.FileNode.path_key == path_key)
        ).scalar_one_or_none()

    def by_id(self, session, id: int) -> m.FileNode | None:
        return session.get(m.FileNode, id)

    def roots(self, session) -> list[m.FileNode]:
        return list(session.execute(
            select(m.FileNode).where(m.FileNode.registered_root)
            .order_by(m.FileNode.path)
        ).scalars())

    def stale(self, session, limit: int | None = None) -> list[m.FileNode]:
        stmt = (
            select(m.FileNode)
            .where(m.FileNode.kind == "file")
            .where(or_(
                m.FileNode.status == "pending",
                m.FileNode.index_hash.is_distinct_from(m.FileNode.content_hash),
            ))
            .order_by(m.FileNode.registered_root.desc(),
                      m.FileNode.mtime.desc().nullslast())
        )
        if limit:
            stmt = stmt.limit(limit)
        return list(session.execute(stmt).scalars())

    def neighbors(self, session, file_id: int, rels: tuple[str, ...],
                  *, limit: int = 20) -> list[m.FileNode]:
        edge_rels = tuple(r for r in rels if r in ("contains", "references"))
        ids: set[int] = set()
        if edge_rels:
            ids |= set(session.execute(
                select(m.FileEdge.dst_id).where(
                    m.FileEdge.src_id == file_id, m.FileEdge.rel.in_(edge_rels))
            ).scalars())
            ids |= set(session.execute(
                select(m.FileEdge.src_id).where(
                    m.FileEdge.dst_id == file_id, m.FileEdge.rel.in_(edge_rels))
            ).scalars())
        if "shares_entity" in rels:
            mine = select(
                m.FileEntityLink.etype, m.FileEntityLink.entity_id
            ).where(m.FileEntityLink.file_id == file_id).subquery()
            ids |= set(session.execute(
                select(m.FileEntityLink.file_id)
                .join(mine, (m.FileEntityLink.etype == mine.c.etype)
                      & (m.FileEntityLink.entity_id == mine.c.entity_id))
                .where(m.FileEntityLink.file_id != file_id)
            ).scalars())
        ids.discard(file_id)
        if not ids:
            return []
        return list(session.execute(
            select(m.FileNode).where(m.FileNode.id.in_(list(ids)[:limit]))
        ).scalars())

    # --- writes --------------------------------------------------------
    def upsert_node(self, session, *, path: str, path_key: str,
                    parent_key: str | None, kind: str, **fields) -> m.FileNode:
        node = self.get(session, path_key)
        if node is None:
            node = m.FileNode(path=path, path_key=path_key,
                              parent_key=parent_key, kind=kind, **fields)
            session.add(node)
            session.flush()
            return node
        node.path = path
        node.parent_key = parent_key
        node.kind = kind
        for k, v in fields.items():
            setattr(node, k, v)
        session.flush()
        return node

    def register(self, session, path: Path, gate: AccessGate,
                 config: FilesConfig) -> RegisterResult:
        # Registering a folder IS the authorization — the user picked this exact
        # path. The allowlist_roots only gate *implicit* access (phrase-resolved
        # "open the folder called X", raw file serving). We still refuse a path
        # that resolves nowhere, sits behind a symlink escape, or is itself an
        # excluded junk dir (.git, node_modules, …).
        if not path.exists():
            raise AccessDenied(str(path), "path does not resolve")
        if gate.is_excluded(path):
            raise AccessDenied(str(path), "matches an exclude pattern")
        if gate._is_symlink_escape(path):
            raise AccessDenied(str(path), "symlink (follow_symlinks is off)")
        is_dir = path.is_dir()
        root = self.upsert_node(
            session, path=str(path), path_key=gate.key(path),
            parent_key=_parent_key(gate, path),
            kind="dir" if is_dir else "file",
            registered_at=dt.datetime.now(dt.timezone.utc),
            registered_root=True,
        )
        discovered = 0
        skipped: list[str] = []
        if is_dir:
            for fp in walk_dir(path, config, gate):
                self.upsert_node(
                    session, path=str(fp.path), path_key=gate.key(fp.path),
                    parent_key=gate.key(fp.path.parent), kind="file",
                    mime=fp.mime, media_kind=fp.media_kind,
                    size_bytes=fp.size, mtime=fp.mtime, status="pending",
                )
                discovered += 1
        return RegisterResult(root_id=root.id, discovered=discovered, skipped=skipped)

    def link_entity(self, session, file_id: int, etype: str, entity_id: int,
                    *, source: str = "summary") -> None:
        row = session.execute(
            select(m.FileEntityLink).where(
                m.FileEntityLink.file_id == file_id,
                m.FileEntityLink.etype == etype,
                m.FileEntityLink.entity_id == entity_id)
        ).scalar_one_or_none()
        if row is None:
            session.add(m.FileEntityLink(file_id=file_id, etype=etype,
                                         entity_id=entity_id, source=source))
        else:
            row.mentions += 1
        session.flush()

    def add_edge(self, session, src_id: int, dst_id: int, rel: str,
                 detail: str | None = None) -> None:
        if src_id == dst_id:
            return
        exists = session.execute(
            select(m.FileEdge.id).where(
                m.FileEdge.src_id == src_id, m.FileEdge.dst_id == dst_id,
                m.FileEdge.rel == rel)
        ).scalar_one_or_none()
        if exists is None:
            session.add(m.FileEdge(src_id=src_id, dst_id=dst_id, rel=rel, detail=detail))
            session.flush()

    def forget(self, session, path_key: str) -> int:
        # Filter in Python: SQL LIKE treats a backslash (Windows path_key) as an
        # escape char, so a startswith() pattern match is unreliable here.
        stem = path_key.rstrip("/").rstrip(os.sep)
        prefixes = (stem + os.sep, stem + "/")
        rows = [
            r for r in session.execute(select(m.FileNode)).scalars()
            if r.path_key == path_key or r.path_key.startswith(prefixes)
        ]
        for r in rows:
            session.delete(r)
        session.flush()
        return len(rows)

    def status_summary(self, session) -> dict:
        base = select(func.count()).select_from(m.FileNode).where(m.FileNode.kind == "file")
        total = session.execute(base).scalar_one()
        indexed = session.execute(base.where(m.FileNode.status == "ok")).scalar_one()
        errors = session.execute(
            base.where(m.FileNode.status.in_(("unreadable", "too_large", "missing")))
        ).scalar_one()
        pending = session.execute(base.where(m.FileNode.status == "pending")).scalar_one()
        stale = len(self.stale(session))
        return {
            "total": total, "indexed": indexed, "stale": stale,
            "pending": pending, "errors": errors,
            "roots": [{"path": r.path, "kind": r.kind} for r in self.roots(session)],
        }
