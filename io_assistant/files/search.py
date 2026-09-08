from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select, text as sqltext

from io_assistant.config import FilesConfig, ResolverConfig
from io_assistant.db import models as m
from io_assistant.files.index import FileIndexer
from io_assistant.files.paths import AccessGate
from io_assistant.files.store import FileIndex
from io_assistant.models_domain import FileHit
from io_assistant.query.entities import resolve_query_entities
from io_assistant.resolve.resolver import EntityResolver

__all__ = ["FileSearcher", "FileAnswer"]

_RELS = ("contains", "references", "shares_entity")
_ENTITY_MODEL = {"person": m.Person, "place": m.Place, "item": m.Item, "occasion": m.Occasion}
_ENTITY_NAME = {
    "person": m.Person.canonical_name, "place": m.Place.name,
    "item": m.Item.name, "occasion": m.Occasion.name,
}


@dataclass
class FileAnswer:
    text: str
    shape: str
    hits: list[FileHit] = field(default_factory=list)
    searched: int = 0


@dataclass
class _Cand:
    file_id: int
    lexical: float = 0.0
    similarity: float = 0.0
    entity: float = 0.0
    neighbor: float = 0.0
    why: str = ""


class FileSearcher:
    def __init__(self, embedder, backend, config: FilesConfig,
                 resolver_cfg: ResolverConfig):
        self._embed = embedder
        self._backend = backend
        self._cfg = config
        self._resolver_cfg = resolver_cfg
        self._index = FileIndex(lambda: None)
        self._indexer = FileIndexer(embedder, backend, config, resolver_cfg)

    def search(self, session, question: str, now, *, gate: AccessGate,
               context: str | None = None) -> FileAnswer:
        cands: dict[int, _Cand] = {}

        def bump(fid, *, why="", **kw):
            c = cands.setdefault(fid, _Cand(file_id=fid))
            for k, v in kw.items():
                setattr(c, k, max(getattr(c, k), v))
            if why and not c.why:
                c.why = why

        tsq = func.plainto_tsquery("english", question)

        # 1a lexical: FTS on chunks
        for fid, rank in session.execute(
            select(m.FileChunk.file_id, func.ts_rank(m.FileChunk.tsv, tsq).label("r"))
            .where(m.FileChunk.tsv.op("@@")(tsq))
            .order_by(sqltext("r DESC")).limit(30)
        ).all():
            bump(fid, lexical=float(rank), why=f'matches "{question[:40]}"')

        # 1a lexical: ILIKE on node title/path/summary
        like = f"%{question.strip()[:60]}%"
        for fid in session.execute(
            select(m.FileNode.id).where(m.FileNode.kind == "file").where(
                m.FileNode.title.ilike(like) | m.FileNode.path.ilike(like)
                | m.FileNode.summary.ilike(like)).limit(15)
        ).scalars():
            bump(fid, lexical=0.5, why="name/summary match")

        # 1b semantic
        qvec = self._embed.embed_one(question)
        for fid, dist in session.execute(
            select(m.FileChunk.file_id,
                   m.FileChunk.embedding.cosine_distance(qvec).label("d"))
            .order_by(sqltext("d ASC")).limit(30)
        ).all():
            bump(fid, similarity=1.0 - float(dist), why="similar content")
        for fid, dist in session.execute(
            select(m.FileNode.id,
                   m.FileNode.embedding.cosine_distance(qvec).label("d"))
            .where(m.FileNode.embedding.isnot(None))
            .order_by(sqltext("d ASC")).limit(15)
        ).all():
            bump(fid, similarity=1.0 - float(dist), why="similar summary")

        # 1c entity
        names = [w.strip(".,!?") for w in question.split() if w[:1].isupper()]
        if names:
            resolver = EntityResolver(session, self._embed, self._resolver_cfg)
            by_type = resolve_query_entities(resolver, session, names)
            for etype, ids in by_type.items():
                for eid in ids:
                    for fid, ename in session.execute(
                        select(m.FileEntityLink.file_id, _ENTITY_NAME[etype])
                        .join(_ENTITY_MODEL[etype],
                              _ENTITY_MODEL[etype].id == m.FileEntityLink.entity_id)
                        .where(m.FileEntityLink.etype == etype,
                               m.FileEntityLink.entity_id == eid)
                    ).all():
                        bump(fid, entity=1.0, why=f"mentions {ename}")

        # 1d graph expansion (one hop)
        for fid in list(cands):
            for nb in self._index.neighbors(session, fid, _RELS, limit=8):
                bump(nb.id, neighbor=0.3, why="linked to a match")

        searched = len(cands)
        if not cands:
            return FileAnswer("I don't have any files that cover that yet.",
                              "text", [], 0)

        nodes = {n.id: n for n in session.execute(
            select(m.FileNode).where(m.FileNode.id.in_(list(cands)))
        ).scalars()}
        scored: list[tuple[float, _Cand, m.FileNode]] = []
        for c in cands.values():
            n = nodes.get(c.file_id)
            if n is None or n.kind != "file":
                continue
            age_days = (
                max(0.0, (now - n.mtime).total_seconds() / 86400) if n.mtime else 365
            )
            recency = math.exp(-age_days / 45)
            score = (0.30 * recency + 0.30 * c.similarity
                     + 0.20 * min(c.lexical, 1.0) + 0.15 * c.entity
                     + 0.05 * c.neighbor)
            scored.append((score, c, n))
        scored.sort(key=lambda s: s[0], reverse=True)
        kept = scored[: self._cfg.retrieval_file_limit]

        # 3 freshness
        final: list[tuple[_Cand, m.FileNode]] = []
        for _, c, n in kept:
            p = Path(n.path)
            if not p.exists():
                n.status = "missing"
                session.flush()
                continue
            self._indexer.index_path(session, p, gate=gate, force=False)
            session.refresh(n)
            final.append((c, n))
        if not final:
            return FileAnswer("I don't have any files that cover that yet.",
                              "text", [], searched)

        # 4 answer
        payload = []
        hits: list[FileHit] = []
        for c, n in final:
            excerpts = list(session.execute(
                select(m.FileChunk.text).where(m.FileChunk.file_id == n.id)
                .order_by(m.FileChunk.ord).limit(3)
            ).scalars())
            payload.append({"path": n.path, "title": n.title,
                            "summary": n.summary or "", "excerpts": excerpts})
            hits.append(FileHit(path=n.path, title=n.title,
                                why=c.why or "match", media_kind=n.media_kind))
        answer = self._backend.answer_from_files(question, payload, "text",
                                                 context=context)
        return FileAnswer(answer.strip(), "text", hits, searched)
