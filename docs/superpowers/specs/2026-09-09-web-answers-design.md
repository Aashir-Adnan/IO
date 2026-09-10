# Design: web-backed answers — three tiers, minimal AI

**Status:** approved 2026-09-09, building. Extends `rules/local-first.md`.

"What's the news on Korea?" / "price of petrol today vs yesterday?" — IO is a
closed-world assistant today (general-knowledge → `unknown`). This adds an
opt-in web path that keeps AI use near zero for the common shapes.

## Prime-directive stance

The default web engine is a **self-hosted SearXNG** running in IO's own Docker
stack (`localhost` — barely an exception; no third party sees the query). A
cloud search provider is an opt-in `[web] provider` for users who don't want
to run the container. Page fetches go direct to the result URLs. `rules/
local-first.md` gains: SearXNG's local port always; `provider != "searxng"` +
its endpoint only when explicitly configured.

## Config

```toml
[web]
enabled       = false          # master switch
provider      = "searxng"      # "searxng" | "none"   (cloud providers later)
searxng_url   = "http://localhost:8888"
max_pages     = 4              # pages fetched for a synthesis answer
fetch_bytes   = 400_000        # per-page cap
news_ttl_min  = 30
fact_ttl_min  = 360
```

`[web].enabled = false` → the `web` action is not registered and the routing
pre-check is skipped; general-knowledge stays `unknown` exactly as now.

## Tier A — instant answers (0 AI, 0 page fetches)

SearXNG's JSON response carries `infoboxes` / `answers` (Wikidata, currency,
units, calculator, Wikipedia lead). For "USD to PKR", "population of Seoul",
"50 miles in km", the value is already there. `web/answer.py` checks these
first and, when one is confident, **templates the reply in Python** — no fetch,
no model.

## Tier B — trackable facts become memory (0 AI at question time)

The petrol case. Rather than search every time:

- **`track` action** ("track the petrol price", "keep an eye on USD to PKR")
  → registers a `tracker` row: a label, a source URL, and a
  selector/extractor spec (CSS path or a JSON pointer or a regex) chosen from a
  small built-in `web/trackers.py` catalogue keyed by the label, or supplied.
- A background job (`web/poller.py`, runs on the service loop, cheap `httpx`
  GET) fetches each tracker once per its interval and writes a **record**:
  `kind="reading", domain=<tracker.domain>, title=<label>,
  attributes={value, unit, source}, occurred_at=<fetch time>`.
- **"price of petrol today vs yesterday"** is then a plain **query over IO's
  own records**. `query/plan.py` already parses `aggregation` (`latest`,
  `count`); `query/compile.py` grows the branch to compile it (this is the
  open "Plan 2 follow-up" in backlog.md). The today-vs-yesterday delta is
  deterministic Python in `query/respond.py` — the model only phrases the
  final sentence from the two grounded rows (or a template does).

So web data is fetched once, stored as memory, and every later question is
local.

## Tier C — news / open synthesis (exactly 1 cached AI call)

1. `web/search.py` — SearXNG search → top `max_pages` URLs + snippets.
2. `web/fetch.py` — `httpx` GET each, extract main text with a **stdlib
   `html.parser`** reader (strip script/style/nav/header/footer/aside, keep the
   longest text blocks), trim to ~400 tokens.
3. **One** call — reuse `Backend.answer_from_files` shape: pass the pages as
   `[{path=url, title, summary=snippet, excerpts=[text]}]`, ask for ≤3
   sentences with citations.
4. Write `web_cache`.

## Cache

Migration 0007 — `web_cache(query_norm PK-ish, kind, answer, sources jsonb,
fetched_at, expires_at)`. `web/answer.py` returns a cache hit with zero network
/ AI when `now < expires_at`. TTL from `[web]` by `kind`
(news / fact / instant).

## Routing

`orchestrator._web_precheck(text)` — regex, no model:
- `\bnews\b.*\b(on|about|in)\b`, `latest on`, `what'?s happening` → `web/news`
- `\bprice of\b`, `how much (is|does)`, `\b(rate|forecast|score)\b`,
  `X today`, `current X` → `web/fact` (tries Tier A, then B if a tracker
  exists, then C)

Ambiguous → the existing single `decide` call, which gains a `web` action in
the registry. No extra LLM call in either path.

## New tree

```
io_assistant/web/
  __init__.py
  search.py     WebSearcher — SearXNG JSON client (+ "none" no-op)
  fetch.py      fetch_and_extract(url) -> (title, text)   stdlib only
  answer.py     web_answer(question, kind) -> WebAnswer    tier A/C + cache
  trackers.py   built-in source catalogue + Tracker model helpers
  poller.py     TrackerPoller — background loop, writes `reading` records
io_assistant/db/migrations/versions/0007_web.py   web_cache + trackers tables
```

## Phasing

1. **DONE** — `WebConfig` in `config.py` + commented `[web]` block in
   `config.toml`; `rules/local-first.md` cases 3–5; migration `0007_web.py`
   (`web_cache` + `trackers`) + `WebCache`/`Tracker` models; `docker-compose`
   `searxng` service + `scripts/searxng/settings.yml` (JSON output);
   `dev.ps1` `Test-WebEnabled` gate — SearXNG starts only when `[web].enabled`.
2. **DONE** — `web/search.py` (SearXNG JSON), `web/fetch.py` (stdlib
   `html.parser`), `web/answer.py` (`WebAnswerer`: cache → Tier A template →
   Tier C `answer_from_files`). `GET /web?q=&kind=` smoke endpoint (404 when
   off). Tests: `test_web_fetch/search/answer`, `test_service_web`.
3. **DONE** — `web` capability (`requires_web`) + `describe_capabilities(web_enabled=)`
   + `decide.txt` exception line; `Orchestrator._web_precheck` (regex, first
   -person guard), `_run_web`, `_action_web`, `WebCard`/`WebSource` + frontend
   `card.js` `web` branch + `globe` icon. `_run_action` now degrades an
   unhandled slug to a query. Tests: `test_orchestrator_web`.
4. **DONE** — `web/trackers.py` (`CATALOGUE`, `match_catalogue`, regex/instant
   `extract_reading` — no model) + `web/poller.py` (`register_tracker`,
   `poll_tracker` → `reading` Records, `latest_readings`, `delta_reading` pure
   today-vs-prior-day, `TrackerPoller` daemon). `track` capability +
   `_action_track` + `_tracker_answer` (Tier B runs first in `_run_web`).
   Started in `create_app` when `[web].enabled`. Tests: `test_web_trackers`,
   `test_web_poller`, `test_orchestrator_web`. NOTE: `query/compile.py`
   aggregation branch NOT done — the delta lives in `poller.delta_reading`
   instead, which is enough for the "today vs yesterday" case.
5. **DONE (docs)** — `.claude/knowledge/web-answers.md`. Precheck cases are
   covered by `test_orchestrator_web` parametrize rather than a JSON fixture
   (the decide eval config has `[web]` off, so `web`/`track` steps can't
   appear there).

Each phase is shippable; 1–3 deliver the news + instant-fact cases.
