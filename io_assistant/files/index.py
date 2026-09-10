from __future__ import annotations

import datetime as dt
import hashlib
import os
from pathlib import Path

from sqlalchemy import select

from io_assistant.backend.interface import BackendParseError
from io_assistant.config import FilesConfig, ResolverConfig
from io_assistant.db import models as m
from io_assistant.files.chunk import chunk_text
from io_assistant.files.extract import read_document
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.files.thumbs import exif_captured_at, make_thumb
from io_assistant.files.walk import classify_media
from io_assistant.query.entities import resolve_query_entities
from io_assistant.resolve.resolver import EntityResolver

__all__ = ["FileIndexer"]

_SEPS = ("/", "\\")


def _hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class FileIndexer:
    def __init__(self, embedder, backend, config: FilesConfig,
                 resolver_cfg: ResolverConfig):
        self._embed = embedder
        self._backend = backend
        self._cfg = config
        self._resolver_cfg = resolver_cfg
        self._index = FileIndex(lambda: None)

    def index_path(self, session, path: Path, *, gate: AccessGate,
                   force: bool = False) -> m.FileNode:
        pk = gate.key(path)
        parent_key = gate.key(path.parent) if path.parent != path else None

        if not path.exists():
            return self._index.upsert_node(
                session, path=str(path), path_key=pk, parent_key=parent_key,
                kind="file", status="missing", error="file not found")

        st = path.stat()
        content_hash = _hash(path)
        node = self._index.get(session, pk)
        if (not force and node is not None and node.status == "ok"
                and node.index_hash == content_hash):
            return node

        media_kind = classify_media(path.suffix, self._cfg)
        node = self._index.upsert_node(
            session, path=str(path), path_key=pk, parent_key=parent_key,
            kind="file", media_kind=media_kind, size_bytes=st.st_size,
            content_hash=content_hash,
            mtime=dt.datetime.fromtimestamp(st.st_mtime, tz=dt.timezone.utc),
        )

        if media_kind is not None:
            if media_kind == "image":
                node.captured_at = exif_captured_at(path)
            out_dir = Path(os.path.expanduser(self._cfg.thumbs_dir))
            thumb = make_thumb(path, media_kind, out_dir, path_key=pk)
            node.thumb_path = str(thumb) if thumb is not None else None
            node.status = "ok"
            node.index_hash = content_hash
            node.indexed_at = dt.datetime.now(dt.timezone.utc)
            session.flush()
            self._contains_edge(session, node, gate)
            return node

        doc = read_document(path, self._cfg)
        if doc.status != "ok":
            node.status = doc.status
            node.error = doc.error
            node.title = doc.title or path.stem
            node.index_hash = content_hash
            node.indexed_at = dt.datetime.now(dt.timezone.utc)
            session.flush()
            return node

        session.query(m.FileChunk).filter_by(file_id=node.id).delete()
        chunks = chunk_text(
            doc.text, chunk_tokens=self._cfg.chunk_tokens,
            overlap=self._cfg.chunk_overlap,
            max_chunks=self._cfg.max_chunks_per_file)
        if chunks:
            vecs = self._embed.embed(chunks)
            for i, (c, v) in enumerate(zip(chunks, vecs)):
                session.add(m.FileChunk(file_id=node.id, ord=i, text=c,
                                        token_estimate=len(c) // 4, embedding=v))

        try:
            res = self._backend.summarize_file(doc.title, doc.text, mime=node.mime)
        except BackendParseError:
            res = {"summary": doc.text[:200], "names": [], "references": []}
        summary = (res.get("summary") or doc.text[:200])[:400]
        node.summary = summary
        node.title = doc.title or path.stem
        node.embedding = self._embed.embed_one(summary)

        resolver = EntityResolver(session, self._embed, self._resolver_cfg)
        names = res.get("names", [])
        by_type = resolve_query_entities(resolver, session, names)
        linked_norm: dict[str, tuple[str, int]] = {}
        for etype, ids in by_type.items():
            for eid in ids:
                self._index.link_entity(session, node.id, etype, eid, source="summary")
        # tokenised tags from the summary + the names the model pulled out
        try:
            from io_assistant.files.tags import TagSpec, salient_terms, write_tags
            from io_assistant.models_domain import ExtractionResult

            specs = list(salient_terms(ExtractionResult(), summary, "", topic_source=True))
            specs += [TagSpec(term=n, norm=n.strip().lower(), kind="topic")
                      for n in names if n and n.strip()]
            write_tags(session, node.id, node.media_kind, specs, source="summary")
        except Exception:  # noqa: BLE001 - tags are best-effort
            pass

        self._reference_edges(session, node, res.get("references", []))
        self._contains_edge(session, node, gate)

        node.status = "ok"
        node.index_hash = content_hash
        node.indexed_at = dt.datetime.now(dt.timezone.utc)
        session.flush()
        return node

    def _contains_edge(self, session, node: m.FileNode, gate: AccessGate) -> None:
        if node.parent_key is None:
            return
        parent = self._index.get(session, node.parent_key)
        if parent is None:
            parent_path = Path(node.path).parent
            parent = self._index.upsert_node(
                session, path=str(parent_path), path_key=node.parent_key,
                parent_key=gate.key(parent_path.parent)
                if parent_path.parent != parent_path else None,
                kind="dir")
        self._index.add_edge(session, parent.id, node.id, "contains")

    def _reference_edges(self, session, node: m.FileNode, refs: list[str]) -> None:
        for raw in refs:
            base = raw.strip().replace("\\", "/").rstrip("/").rsplit("/", 1)[-1].lower()
            if not base or "." not in base:
                continue
            # basename LIKE match (no separators in `base` -> safe pattern),
            # then verify a real path-boundary in Python.
            for cand in session.execute(
                select(m.FileNode).where(m.FileNode.id != node.id).where(
                    m.FileNode.path_key.ilike("%" + base))
            ).scalars():
                key = cand.path_key.lower()
                before = key[: -len(base)]
                if not before or before[-1] in _SEPS:
                    self._index.add_edge(session, node.id, cand.id,
                                         "references", detail=raw)
                    break
