# Web-backed answers (opt-in, 2026-09-09)

Spec: `docs/superpowers/specs/2026-09-09-web-answers-design.md`. Off unless
`config.toml [web].enabled = true`. When off: the `web`/`track` capabilities
are not registered, `_web_precheck` returns None, general-knowledge stays
`unknown` — nothing changed.

## Prime-directive stance

`rules/local-first.md` cases 3–5 cover it: a **self-hosted SearXNG** on
`localhost:8888` (IO's own Docker stack — the query never leaves the machine),
plain GETs to result URLs for Tier C, and a future cloud search provider slot.
One synthesis call per uncached news/open question goes to `api.anthropic.com`
when the backend is anthropic/hybrid (same boundary as `answer_from_files`).

## Three tiers (minimal AI)

| Tier | What | AI | Network |
|---|---|---|---|
| A | SearXNG `answers`/`infoboxes` (currency, wikidata, calculator) → templated in Python | none | 1 SearXNG call |
| B | `track` a figure → poller writes `reading` records → later questions are queries over memory | none | 1 poll per interval |
| C | news / open synthesis: search → fetch top `max_pages` → `answer_from_files` | 1 call, cached | search + N GETs |

`web_cache(query_norm, kind)` unique; TTL by kind (`news_ttl_min` /
`fact_ttl_min` / `instant_ttl_min`). A cache hit inside the TTL = 0 network,
0 AI.

## Package `io_assistant/web/`

| module | role |
|---|---|
| `search.py` | `WebSearcher(config.web)` — SearXNG `format=json` client. `.enabled` gate; `provider="none"` and `enabled=False` are no-ops (no socket). Parses `answers`/`infoboxes` → `InstantAnswer`, `results` → `WebResult`. |
| `fetch.py` | `fetch_and_extract(url)` → `PageText(url,title,text)`. stdlib `html.parser` only (`_Reader`): drops script/style/nav/header/footer/aside/form, keeps prose lines. `extract_text(html)` is pure (tested directly). Streams, caps at `fetch_bytes`, trims to ~4k chars. |
| `answer.py` | `WebAnswerer(config, backend)` — `answer(session, q, *, kind, now)`. `kind` ∈ {news, fact}. Order: cache → (fact only) Tier A template → Tier C. Writes `web_cache`. Returns `WebAnswer(text, kind, tier, sources, cached)` or `None` (caller → `unknown`). Deterministic Python owns normalisation / TTL / tier choice / source list; the model is called **only** in `_tier_c`, only on a miss. |
| `trackers.py` | Pure. `CATALOGUE` of `TrackerSpec` (usd-pkr, gbp-pkr, bitcoin, gold). `match_catalogue(text)` substring-matches the `matcher` keys. `extractor` spec: `{"type":"instant","query":...}` (parse a number out of a SearXNG instant answer) or `{"type":"regex","pattern":...,"unit":...}` (over fetched page text). `value_from_text` / `extract_reading` — regex only, no model. |
| `poller.py` | `register_tracker` (upsert by `norm`), `due_trackers`, `poll_tracker` (fetch → `extract_reading` → `_write_reading` a `reading` Record with a synthetic `source="web"` utterance), `poll_due`. `latest_readings(session, label)` / `delta_reading(readings, now)` — latest vs most-recent-earlier-calendar-day, change + pct, **pure Python** (no SQL date math). `TrackerPoller` — daemon thread, `tick_min` cycle, modelled on `files.queue.IndexQueue`; started in `create_app` when `[web].enabled`. |

## Routing (no extra LLM call)

`Orchestrator._web_precheck(text)` — regex, runs before the planner:
- first-person (`my`/`I`/`we`…) → None (it's about the user's own life)
- `track|keep an eye on|watch|monitor` + `match_catalogue` hit → `"track"`
- `news|headlines|latest on|what's happening` → `"news"`
- `price of|exchange rate|how much is|USD…to…|current … price|weather` → `"fact"`

`"track"` → `_action_track`. `"news"`/`"fact"` → `_run_web` → Tier B
(`_tracker_answer`, registers+polls a known figure if not yet tracked) then
Tier A/C (`WebAnswerer`). `None` from `_run_web` → falls through to the normal
`decide` planner, which has `web` + `track` action steps (`requires_web`, shown
only when `web_enabled`). `_run_action` degrades an unhandled slug to a query.

`HandleResult` carries a `WebCard(tier, kind, sources, cached)`; frontend
`components/card.js` `web` branch renders a `globe` glyph + source hostnames.

## Tests

`test_web_fetch`, `test_web_search`, `test_web_answer`, `test_web_trackers`,
`test_web_poller`, `test_service_web`, `test_orchestrator_web`. FakeSearcher /
monkeypatched `fetch_and_extract` — no real network in the suite.

## Not done / deferred

Cloud search providers (`provider` only accepts `searxng`/`none`). `regex`
trackers have no catalogue entry yet (petrol needs a known source page). No
`io web`/`io track` CLII surface. No frontend settings toggle for `[web]`.
`query/compile.py` still ignores the parsed `aggregation` field — the
today-vs-yesterday delta is done entirely in `web/poller.delta_reading`, not
the general query pipeline.
