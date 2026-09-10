"""WebSearcher — SearXNG JSON parsing + the disabled no-op."""
from __future__ import annotations

import httpx
import pytest

from io_assistant.config import WebConfig
from io_assistant.web import search as search_mod
from io_assistant.web.search import WebSearcher, WebSearchError

_SEARX_JSON = {
    "query": "usd to pkr",
    "answers": [{"answer": "1 USD = 278.5 PKR", "url": "https://x.test/fx"}],
    "infoboxes": [
        {"infobox": "Pakistani rupee", "content": "The rupee is the currency of Pakistan.",
         "urls": [{"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/PKR"}]}
    ],
    "results": [
        {"title": "XE rate", "url": "https://xe.test/pkr", "content": "Live rate 278.",
         "engine": "duckduckgo"},
        {"title": "no url", "content": "skip me"},
        {"title": "Reuters", "url": "https://reuters.test/pkr", "content": "Rupee steady."},
    ],
}


def _mock_httpx(monkeypatch, payload, status=200):
    def handler(request):
        return httpx.Response(status, json=payload)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        search_mod.httpx, "Client",
        lambda **kw: real_client(transport=transport),
    )


def _cfg(**kw):
    return WebConfig(enabled=True, provider="searxng", **kw)


def test_disabled_is_a_noop(monkeypatch):
    called = []
    monkeypatch.setattr(search_mod.httpx, "Client",
                        lambda **kw: called.append(1))
    r = WebSearcher(WebConfig(enabled=False)).search("anything")
    assert r.empty and not called


def test_provider_none_is_a_noop():
    assert WebSearcher(WebConfig(enabled=True, provider="none")).search("x").empty


def test_parses_answers_infoboxes_results(monkeypatch):
    _mock_httpx(monkeypatch, _SEARX_JSON)
    r = WebSearcher(_cfg()).search("usd to pkr")
    assert r.instant[0].text == "1 USD = 278.5 PKR"
    assert r.instant[0].url == "https://x.test/fx"
    assert any(i.kind == "infobox" for i in r.instant)
    urls = [x.url for x in r.results]
    assert urls == ["https://xe.test/pkr", "https://reuters.test/pkr"]  # no-url row dropped
    assert r.results[0].engine == "duckduckgo"


def test_limit_caps_results(monkeypatch):
    _mock_httpx(monkeypatch, _SEARX_JSON)
    r = WebSearcher(_cfg()).search("usd to pkr", limit=1)
    assert len(r.results) == 1


def test_http_error_raises(monkeypatch):
    _mock_httpx(monkeypatch, {}, status=502)
    with pytest.raises(WebSearchError):
        WebSearcher(_cfg()).search("boom")
