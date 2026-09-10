"""WebAnswerer — tier routing, Python templating for Tier A, one model call for
Tier C, and the cache that makes a repeat question free. Real DB (web_cache)."""
from __future__ import annotations

import datetime as dt

import pytest

from io_assistant.web import answer as answer_mod
from io_assistant.web.answer import WebAnswerer, normalize_query
from io_assistant.web.fetch import PageText
from io_assistant.web.search import InstantAnswer, SearchResponse, WebResult

pytestmark = pytest.mark.usefixtures("engine")

NOW = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.timezone.utc)


class FakeSearcher:
    def __init__(self, resp: SearchResponse, enabled: bool = True):
        self._resp = resp
        self.enabled = enabled
        self.calls = 0

    def search(self, query, *, categories="general"):
        self.calls += 1
        return self._resp


def _cfg(config, **web):
    for k, v in {"enabled": True, "provider": "searxng", **web}.items():
        setattr(config.web, k, v)
    return config


def test_normalize_query_trims_punctuation_and_case():
    assert normalize_query("  What's the NEWS on Korea??  ") == "what's the news on korea"


def test_tier_a_templates_in_python_no_model_call(db, config, fake_backend):
    resp = SearchResponse(query="usd to pkr",
                          instant=[InstantAnswer(text="1 USD = 278.5 PKR",
                                                 url="https://x.test/fx")])
    wa = WebAnswerer(_cfg(config), fake_backend, searcher=FakeSearcher(resp))

    ans = wa.answer(db, "USD to PKR?", kind="fact", now=NOW)
    assert ans is not None
    assert ans.tier == "a"
    assert "278.5 PKR" in ans.text
    assert "answer_from_files" not in fake_backend.calls


def test_tier_a_result_is_cached(db, config, fake_backend):
    resp = SearchResponse(query="q", instant=[InstantAnswer(text="42")])
    searcher = FakeSearcher(resp)
    wa = WebAnswerer(_cfg(config), fake_backend, searcher=searcher)

    first = wa.answer(db, "meaning of life?", kind="fact", now=NOW)
    db.flush()
    second = wa.answer(db, "meaning of life?", kind="fact",
                       now=NOW + dt.timedelta(minutes=5))
    assert first.cached is False
    assert second.cached is True
    assert searcher.calls == 1          # second answered from cache


def test_cache_expires(db, config, fake_backend):
    resp = SearchResponse(query="q", instant=[InstantAnswer(text="42")])
    searcher = FakeSearcher(resp)
    config = _cfg(config, instant_ttl_min=10)
    wa = WebAnswerer(config, fake_backend, searcher=searcher)

    wa.answer(db, "q?", kind="fact", now=NOW)
    db.flush()
    wa.answer(db, "q?", kind="fact", now=NOW + dt.timedelta(minutes=30))
    assert searcher.calls == 2          # stale entry re-fetched


def test_tier_c_one_model_call_then_cached(db, config, fake_backend, monkeypatch):
    resp = SearchResponse(
        query="news on korea",
        results=[WebResult(title="KH", url="https://kh.test/a", snippet="A snippet"),
                 WebResult(title="Yon", url="https://yon.test/b", snippet="B snippet")],
    )
    monkeypatch.setattr(
        answer_mod, "fetch_and_extract",
        lambda url, **kw: PageText(url=url, title="Page", text="Long article body " * 20),
    )
    fake_backend.set_file_answer("North Korea did a thing (source: KH).")
    searcher = FakeSearcher(resp)
    wa = WebAnswerer(_cfg(config), fake_backend, searcher=searcher)

    ans = wa.answer(db, "what's the news on korea", kind="news", now=NOW)
    assert ans.tier == "c"
    assert ans.text.startswith("North Korea did a thing")
    assert {s["url"] for s in ans.sources} == {"https://kh.test/a", "https://yon.test/b"}
    assert fake_backend.calls.count("answer_from_files") == 1

    db.flush()
    again = wa.answer(db, "what's the news on korea", kind="news",
                      now=NOW + dt.timedelta(minutes=5))
    assert again.cached is True
    assert fake_backend.calls.count("answer_from_files") == 1   # not called again


def test_disabled_returns_none(db, config, fake_backend):
    resp = SearchResponse(query="q", instant=[InstantAnswer(text="42")])
    config = _cfg(config, enabled=False)
    wa = WebAnswerer(config, fake_backend, searcher=FakeSearcher(resp, enabled=False))
    assert wa.answer(db, "q?", kind="fact", now=NOW) is None


def test_no_results_returns_none(db, config, fake_backend):
    wa = WebAnswerer(_cfg(config), fake_backend,
                     searcher=FakeSearcher(SearchResponse(query="q")))
    assert wa.answer(db, "q?", kind="news", now=NOW) is None
