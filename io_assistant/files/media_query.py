"""Retrieve media by tokenised tags — "fetch all pictures of me and nafay".

Matches `file_tags.norm` exact + trigram-fuzzy, constrained to media kinds,
and ranks by how many of the query's distinct terms a file covers. A file
that covers ALL of them ranks above one that covers some.
"""
from __future__ import annotations

import re

from sqlalchemy import func, or_, select

from io_assistant.db import models as m
from io_assistant.files.tags import SELF_WORDS, query_terms

__all__ = ["media_nodes_for_terms", "expand_self"]

_MEDIA = ("image", "video")
_FUZZ = 0.42   # trigram similarity floor for a near-miss term


def expand_self(terms: list[str], owner_name: str) -> list[str]:
    out: list[str] = []
    for t in terms:
        lw = (t or "").strip().lower()
        if not lw:
            continue
        if lw in SELF_WORDS or lw == "self":
            for x in ("me", (owner_name or "").strip().lower()):
                if x and x not in out:
                    out.append(x)
            continue
        if lw not in out:
            out.append(lw)
    return out


def media_nodes_for_terms(session, terms, *, owner_name: str = "",
                          media_kinds=_MEDIA, limit: int = 60):
    """Return (nodes, matched_all: bool) — FileNodes ranked by tag coverage."""
    norms = expand_self(list(terms), owner_name)
    if not norms:
        # no constraint → newest media
        nodes = session.execute(
            select(m.FileNode)
            .where(m.FileNode.kind == "file",
                   m.FileNode.media_kind.in_(list(media_kinds)))
            .order_by(func.coalesce(m.FileNode.captured_at, m.FileNode.mtime,
                                    m.FileNode.created_at).desc())
            .limit(limit)
        ).scalars().all()
        return nodes, False

    # per-file: which query norms did it hit — exact, whole-word containment
    # ("cnic" in "cnic card", "passport" in "my passport"), or close trigram
    hits: dict[int, set[str]] = {}
    for norm in norms:
        wb = r"\y" + re.escape(norm) + r"\y"
        rows = session.execute(
            select(m.FileTag.file_id)
            .join(m.FileNode, m.FileNode.id == m.FileTag.file_id)
            .where(m.FileNode.media_kind.in_(list(media_kinds)))
            .where(or_(
                m.FileTag.norm == norm,
                m.FileTag.norm.op("~")(wb),                 # norm is a word in the tag
                func.similarity(m.FileTag.norm, norm) >= _FUZZ,
            ))
        ).scalars().all()
        for fid in rows:
            hits.setdefault(fid, set()).add(norm)

    if not hits:
        return [], False

    want = len(set(norms))
    ranked = sorted(hits.items(), key=lambda kv: (-len(kv[1]),))
    ids = [fid for fid, _ in ranked][:limit]
    matched_all = any(len(s) == want for s in hits.values())

    nodes = {n.id: n for n in session.execute(
        select(m.FileNode).where(m.FileNode.id.in_(ids))
    ).scalars()}
    return [nodes[i] for i in ids if i in nodes], matched_all


def terms_from_question(question: str, owner_name: str) -> list[str]:
    return query_terms(question, owner_name)
