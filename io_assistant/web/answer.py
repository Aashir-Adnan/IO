"""web_answer — the router between the three tiers, and the only place a model
is (sometimes) called.

Deterministic Python owns: query normalisation, cache lookup/TTL, which tier
runs, and the source list. The model is asked exactly one thing, only in
Tier C, only on a cache miss: phrase <=3 sentences from the page excerpts it is
handed (`Backend.answer_from_files`). Tier A and cache hits never call it.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from sqlalchemy import select

from io_assistant.config import Config
from io_assistant.db import models as m
from io_assistant.progress import emit as _emit
from io_assistant.web.fetch import WebFetchError, fetch_and_extract
from io_assistant.web.search import SearchResponse, WebSearcher, WebSearchError

__all__ = ["WebAnswer", "WebAnswerer"]

_WS = re.compile(r"\s+")


@dataclass
class WebAnswer:
    text: str
    kind: str                      # news | fact | instant
    tier: str                      # a | c | cache
    sources: list[dict] = field(default_factory=list)   # [{title, url}]
    cached: bool = False


def normalize_query(q: str) -> str:
    q = _WS.sub(" ", (q or "").strip().lower())
    return q.rstrip("?.! ")


class WebAnswerer:
    def __init__(self, config: Config, backend, searcher: WebSearcher | None = None):
        self._config = config
        self._backend = backend
        self._web = config.web
        self._searcher = searcher or WebSearcher(config.web)

    @property
    def enabled(self) -> bool:
        return self._searcher.enabled

    def _ttl_min(self, kind: str) -> int:
        return {
            "news": self._web.news_ttl_min,
            "fact": self._web.fact_ttl_min,
            "instant": self._web.instant_ttl_min,
        }.get(kind, self._web.fact_ttl_min)

    # -- cache -------------------------------------------------------------
    def _cache_get(self, session, qn: str, kind: str, now: dt.datetime) -> WebAnswer | None:
        row = session.execute(
            select(m.WebCache).where(
                m.WebCache.query_norm == qn, m.WebCache.kind == kind
            )
        ).scalar_one_or_none()
        if row is None or row.expires_at <= now:
            return None
        return WebAnswer(text=row.answer, kind=kind, tier=row.tier,
                         sources=list(row.sources or []), cached=True)

    def _cache_put(self, session, qn: str, ans: WebAnswer, now: dt.datetime) -> None:
        expires = now + dt.timedelta(minutes=self._ttl_min(ans.kind))
        row = session.execute(
            select(m.WebCache).where(
                m.WebCache.query_norm == qn, m.WebCache.kind == ans.kind
            )
        ).scalar_one_or_none()
        if row is None:
            session.add(m.WebCache(
                query_norm=qn, kind=ans.kind, answer=ans.text,
                sources=ans.sources, tier=ans.tier,
                fetched_at=now, expires_at=expires,
            ))
        else:
            row.answer = ans.text
            row.sources = ans.sources
            row.tier = ans.tier
            row.fetched_at = now
            row.expires_at = expires

    # -- entry point ----------------------------------------------------------
    def answer(self, session, question: str, *, kind: str, now: dt.datetime) -> WebAnswer | None:
        """`kind` is "news" | "fact" (chosen by the regex pre-check). Returns
        None when the web path can't help (disabled, no results, fetch/model
        failure) — the caller then falls back to "unknown"."""
        qn = normalize_query(question)
        if not qn:
            return None

        hit = self._cache_get(session, qn, kind, now)
        if hit is not None:
            _emit("Answered from cache")
            return hit
        if kind == "fact":
            hit = self._cache_get(session, qn, "instant", now)
            if hit is not None:
                _emit("Answered from cache")
                return hit

        if not self.enabled:
            return None

        _emit("Searching the web")
        try:
            resp = self._searcher.search(
                question, categories="news" if kind == "news" else "general"
            )
        except WebSearchError:
            return None
        if resp.empty:
            return None

        if kind == "fact":
            a = self._tier_a(resp)
            if a is not None:
                _emit("Found an instant answer")
                self._cache_put(session, qn, a, now)
                return a

        _emit("Reading pages", f"up to {self._web.max_pages}")
        c = self._tier_c(resp, question, kind)
        if c is not None:
            self._cache_put(session, qn, c, now)
        return c

    # -- Tier A: instant answer, templated in Python -------------------------
    @staticmethod
    def _tier_a(resp: SearchResponse) -> WebAnswer | None:
        if not resp.instant:
            return None
        best = resp.instant[0]
        text = best.text
        if len(text) > 400:
            text = text[:397].rstrip() + "…"
        sources = [{"title": "source", "url": best.url}] if best.url else []
        return WebAnswer(text=text, kind="instant", tier="a", sources=sources)

    # -- Tier C: fetch pages, one synthesis call ---------------------------
    def _tier_c(self, resp: SearchResponse, question: str, kind: str) -> WebAnswer | None:
        pages: list[dict] = []
        used: list[dict] = []
        for r in resp.results[: self._web.max_pages]:
            try:
                page = fetch_and_extract(r.url, max_bytes=self._web.fetch_bytes)
            except WebFetchError:
                continue
            body = page.text or r.snippet
            if not body:
                continue
            pages.append({
                "path": r.url,
                "title": page.title or r.title,
                "summary": r.snippet,
                "excerpts": [body[:1500]],
            })
            used.append({"title": page.title or r.title, "url": r.url})
            if len(pages) >= self._web.max_pages:
                break

        if not pages:
            # nothing fetched — fall back to snippets alone if we have them
            if not resp.results:
                return None
            for r in resp.results[:3]:
                if r.snippet:
                    pages.append({"path": r.url, "title": r.title,
                                  "summary": r.snippet, "excerpts": [r.snippet]})
                    used.append({"title": r.title, "url": r.url})
            if not pages:
                return None

        shape = (
            "Answer in <=3 sentences. Lead with the most recent development. "
            "Cite sources inline as (source: <title>)."
            if kind == "news" else
            "Answer in <=2 sentences, just the fact asked for, with the figure "
            "and its date if present. Cite the source inline as (source: <title>)."
        )
        try:
            text = self._backend.answer_from_files(question, pages, shape)
        except Exception:
            return None
        text = (text or "").strip()
        if not text:
            return None
        return WebAnswer(text=text, kind=kind, tier="c", sources=used)
