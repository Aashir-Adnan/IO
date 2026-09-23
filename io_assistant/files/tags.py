"""Tokenized salient terms for a file — the fast, fuzzy layer over
FileEntityLink.

A caption "me and nafay in hunza" on a photo becomes tags:
    ("Nafay", "nafay", "person")   -- + entity link if it resolved
    ("Hunza", "hunza", "place")
    ("Aashir", "aashir", "self")   -- from config.owner_name
    ("Me",     "me",     "self")

Retrieval ("fetch all pictures of me and nafay") tokenises the query the same
way and matches `file_tags.norm` exact + trigram-fuzzy, optionally constrained
to `media_kind`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select

from io_assistant.db import models as m
from io_assistant.models_domain import ExtractionResult

__all__ = ["TagSpec", "salient_terms", "write_tags", "query_terms", "SELF_WORDS"]

SELF_WORDS = {
    "me", "myself", "my", "mine", "i", "i'm", "im",
    "we", "us", "our", "ours", "ourselves",
}
_STOP = {
    "the", "a", "an", "and", "or", "of", "with", "in", "at", "on", "to", "for",
    "from", "by", "all", "any", "some", "show", "fetch", "get", "find", "pull",
    "up", "photo", "photos", "picture", "pictures", "pic", "pics", "image",
    "images", "video", "videos", "clip", "clips", "note", "notes", "file",
    "files", "about", "featuring", "that", "this", "these", "those", "it",
    # generic document/possession suffixes — meaningful inside a tag phrase
    # ("cnic card", "id card") but noise as a standalone query term
    "card", "copy", "scan", "doc", "document", "where", "wheres", "my",
}


def _norm(term: str) -> str:
    return re.sub(r"\s+", " ", term.strip().lower())


@dataclass(frozen=True)
class TagSpec:
    term: str
    norm: str
    kind: str                      # person | place | self | thing | event | topic
    entity_etype: str | None = None
    entity_id: int | None = None


def salient_terms(extraction: ExtractionResult | None, text: str,
                  owner_name: str, *, topic_source: bool = False) -> list[TagSpec]:
    """Build tag specs from an extraction + the raw text. `topic_source=True`
    for file summaries — unresolved capitalised words also become 'topic' tags.
    Entity ids are filled in later by the caller once it has resolved them.
    """
    specs: dict[tuple[str, str], TagSpec] = {}

    def add(term: str, kind: str):
        term = term.strip()
        if not term:
            return
        n = _norm(term)
        if n in _STOP or len(n) < 2:
            return
        specs.setdefault((n, kind), TagSpec(term=term, norm=n, kind=kind))

    ex = extraction or ExtractionResult()
    for p in ex.people:
        add(p.name, "person")
    for pl in ex.places:
        add(pl.name, "place")
    for it in ex.items:
        add(it.name, "thing")
    for oc in ex.occasions:
        add(oc.name, "event")

    # first-/second-person reference → a "self" tag pair
    words = re.findall(r"[a-zA-Z']+", (text or "").lower())
    if any(w in SELF_WORDS for w in words):
        add("Me", "self")
        if owner_name:
            add(owner_name, "self")

    if topic_source:
        known = {s.norm for s in specs.values()}
        for w in re.findall(r"\b([A-Z][a-zA-Z][a-zA-Z-]+)\b", text or ""):
            if _norm(w) not in known:
                add(w, "topic")

    return list(specs.values())


def write_tags(session, file_id: int, media_kind: str | None,
               specs: list[TagSpec], *, source: str, replace: bool = True) -> None:
    if replace:
        session.query(m.FileTag).filter(
            m.FileTag.file_id == file_id, m.FileTag.source == source
        ).delete(synchronize_session=False)
    seen: set[tuple[str, str]] = set()
    for s in specs:
        key = (s.norm, s.kind)
        if key in seen:
            continue
        seen.add(key)
        session.add(m.FileTag(
            file_id=file_id, term=s.term, norm=s.norm, kind=s.kind,
            media_kind=media_kind, entity_etype=s.entity_etype,
            entity_id=s.entity_id, source=source,
        ))
    session.flush()


def query_terms(question: str, owner_name: str) -> list[str]:
    """Normalised terms to look up in file_tags for a retrieval question.
    'pictures of me and nafay in hunza' -> ['me','<owner>','nafay','hunza']."""
    out: list[str] = []
    words = re.findall(r"[A-Za-z][A-Za-z'-]+", question or "")
    for w in words:
        lw = w.lower()
        if lw in SELF_WORDS:
            if "me" not in out:
                out.append("me")
            if owner_name and _norm(owner_name) not in out:
                out.append(_norm(owner_name))
            continue
        if lw in _STOP:
            continue
        if w[0].isupper() or lw not in _COMMON:
            if lw not in out:
                out.append(lw)
    return out


# a small common-word set so lowercase filler ("trip", "went") doesn't become a
# tag term while real nouns do; capitalised words always pass.
_COMMON = {
    "trip", "went", "going", "was", "were", "had", "have", "has", "did", "do",
    "does", "is", "are", "am", "been", "being", "then", "when", "where", "who",
    "what", "which", "there", "here", "back", "over", "out", "into", "onto",
    "day", "days", "time", "times", "year", "years", "week", "weeks", "today",
    "yesterday", "tomorrow", "morning", "evening", "night", "afternoon",
}
