"""SearXNG JSON client. Deterministic parsing only — no model, no ranking
beyond the order SearXNG already returns.

SearXNG's `format=json` response carries:
  answers    - list[str] | list[{answer, url}]  (calculator, currency, DDG...)
  infoboxes  - list[{infobox, content, urls: [{title, url}], ...}]  (Wikidata)
  results    - list[{title, url, content, engine, ...}]  (the web hits)

`provider="none"` is a no-op that opens no socket.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx

from io_assistant.config import WebConfig

__all__ = ["WebResult", "InstantAnswer", "SearchResponse", "WebSearcher", "WebSearchError"]

_TIMEOUT = httpx.Timeout(6.0, connect=3.0)


class WebSearchError(RuntimeError):
    """SearXNG unreachable or returned something unparseable."""


@dataclass(frozen=True)
class WebResult:
    title: str
    url: str
    snippet: str
    engine: str = ""


@dataclass(frozen=True)
class InstantAnswer:
    text: str
    url: str = ""
    kind: str = "answer"          # "answer" | "infobox"


@dataclass
class SearchResponse:
    query: str
    instant: list[InstantAnswer] = field(default_factory=list)
    results: list[WebResult] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.instant and not self.results


def _clean(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


class WebSearcher:
    def __init__(self, config: WebConfig):
        self._config = config

    @property
    def enabled(self) -> bool:
        return self._config.enabled and self._config.provider == "searxng"

    def search(self, query: str, *, categories: str = "general", limit: int = 8) -> SearchResponse:
        query = _clean(query)
        if not self.enabled or not query:
            return SearchResponse(query=query)

        url = self._config.searxng_url.rstrip("/") + "/search"
        params = {"q": query, "format": "json", "categories": categories}
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except (httpx.HTTPError, ValueError) as e:
            raise WebSearchError(f"SearXNG search failed: {e}") from e

        return SearchResponse(
            query=query,
            instant=self._parse_instant(data),
            results=self._parse_results(data, limit),
        )

    @staticmethod
    def _parse_instant(data: dict) -> list[InstantAnswer]:
        out: list[InstantAnswer] = []
        for a in data.get("answers") or []:
            if isinstance(a, dict):
                text = _clean(a.get("answer") or a.get("text"))
                if text:
                    out.append(InstantAnswer(text=text, url=_clean(a.get("url"))))
            else:
                text = _clean(a)
                if text:
                    out.append(InstantAnswer(text=text))
        for box in data.get("infoboxes") or []:
            if not isinstance(box, dict):
                continue
            text = _clean(box.get("content"))
            if not text:
                continue
            urls = box.get("urls") or []
            src = _clean(urls[0].get("url")) if urls and isinstance(urls[0], dict) else ""
            out.append(InstantAnswer(text=text, url=src, kind="infobox"))
        return out

    @staticmethod
    def _parse_results(data: dict, limit: int) -> list[WebResult]:
        out: list[WebResult] = []
        for r in data.get("results") or []:
            if not isinstance(r, dict):
                continue
            u = _clean(r.get("url"))
            if not u:
                continue
            out.append(WebResult(
                title=_clean(r.get("title")) or u,
                url=u,
                snippet=_clean(r.get("content")),
                engine=_clean(r.get("engine")),
            ))
            if len(out) >= limit:
                break
        return out
