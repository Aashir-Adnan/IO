# Design: one "decide" call — unified routing + extraction + actions

**Status:** Phases 1–3 IMPLEMENTED (2026-09-09), verified live on the
`anthropic` backend. Phase 4 (real media-gallery action) + Phase 5
(eval fixtures, cache-tune, local `quality` mode) outstanding.

- Phase 1 — `Plan`/`Step`/`Capability` + `io_assistant/actions/registry.py` +
  `io_assistant/decide/planner.py` (split) + orchestrator dispatch loop.
  Transparent refactor: full suite unchanged. `tests/test_decide_planner.py`.
- Phase 2 — `prompts/decide.txt`, `io_assistant/decide/parse.py:parse_plan`,
  `AnthropicBackend.decide`, `[backend].decide` (`auto` default).
  `tests/test_decide_parse.py`, `test_decide_combined.py`.
- Phase 3 — `Orchestrator._merge_results` (multi-step: gate wins, else
  concat messages + merge cards). Verified: "remind me to submit the report
  tomorrow, and what tasks do I have?" → one turn that stores AND answers.
- Phase 4 — DONE. `show_photos` → a real tag-based `GalleryCard`. New
  **tokenised `file_tags`** (migration 0006, `io_assistant/files/tags.py`):
  a caption "me and nafay in hunza" tags the photo with (Nafay/person),
  (Hunza/place), (Me/self), (<owner>/self). `media_query.py` ranks media by
  tag coverage. `_file_turn` routes "photos/pictures/videos of X" here.
  Verified live: caption a jpg → "fetch all pictures of me and Nafay" →
  a gallery card.
- Phase 5 — DONE (first pass). `tests/fixtures/decide_cases.json` +
  `tests/test_decide_eval.py` (opt-in, `IO_ANTHROPIC_TESTS=1`) — **17/17 on
  Haiku** after tightening the `file` bullet in `decide.txt`. Prompt-cache
  measurement + local-`quality` combined mode still to do.

## The ask

> Provide an LLM the text I said, have it determine what I want to do (store,
> query, pull up a function) and respond with the appropriate workflow /
> function names (could be more than one). If information is given (almost
> always) send the text with chat context + current date + minor details and
> ask for a structured return to store. Minimal token usage, most efficient.

Today it's two LLM calls for a store turn:

```
Router.classify(text, context)      → one word: STORE | QUERY | FILE | UNKNOWN
  (STORE →) Extractor.run(text, now) → ExtractionResult  (JSON mode)
```

One intent only, no chat context in extraction, no notion of "run this
function", and `route` + `extract` are separate round-trips.

## Target

**`decide(utterance, context, now, capabilities) → Plan`** — one call.

```python
class Step(BaseModel):
    kind: Literal["store", "query", "action"]
    # kind == "store":  the structured extraction, inline
    extraction: ExtractionResult | None = None
    # kind == "query":  the sub-question(s), verbatim or lightly rewritten
    question: str | None = None
    # kind == "action": a named capability + its args
    action: str | None = None          # must be in the capability registry
    args: dict = {}

class Plan(BaseModel):
    steps: list[Step]                  # ordered; usually 1, sometimes 2–3
    reply_hint: str | None = None      # optional phrasing seed for the answer
```

- **Multi-intent** falls out for free: "remind me to call mom and what's on
  Friday" → `[Step(store, …), Step(query, "what's on Friday")]`.
- **Actions / functions** are a new `kind`. A **capability registry**
  (`io_assistant/actions/registry.py`) lists the callable workflows the model
  may name — each with a slug, a one-line description, and a JSON arg schema:

  | slug | args | handler |
  |---|---|---|
  | `open_folder` | `{name}` | `files.gallery.open_folder` via phrase resolve |
  | `show_photos` | `{of?}` | gallery card |
  | `start_voice` | `{}` | UI hint |
  | `set_reminder` | (falls back to `store` extraction) | — |
  | `search_files` | `{query}` | `files.search` |

  The prompt gets the registry as a compact list. The model returns
  `action: "<slug>"` + `args`; Python validates the slug + args against the
  schema and dispatches. An unknown slug → treat as `query` (safe default).

- **"Information is given" → always extract.** When `kind == "store"` the model
  returns `extraction` in the same response. Chat `context` and `now` are in
  the prompt, so "he's moving tomorrow" resolves `he` from context and the
  extractor emits a real `when_phrase` that `resolve/dates.py` now grounds
  (`tomorrow, the 10th of september` → 2026-09-10, fixed 2026-09-09).

## The LLM boundary is unchanged

`rules/llm-boundaries.md`: the model still only *routes / extracts / plans /
phrases*. `decide` is route+extract+plan folded into one response. Everything
downstream stays deterministic Python:

- `resolve/` grounds every `when_phrase` / `recurrence_phrase`; the model never
  does date math.
- `resolve/` decides entity identity; `persist/` writes rows; the confidence
  gate is Python.
- `query/compile.py` builds SQL; `query/rank.py` ranks. The model's `question`
  string still goes through the existing planner/compiler — `decide` does not
  emit SQL or filters.
- Action `args` are schema-validated and only ever reach a whitelisted handler.

A weaker model produces a worse `Plan` but still cannot corrupt the datastore.

## Token efficiency

1. **One round-trip** instead of two for a store turn (the common case) — the
   single biggest saving.
2. **Prompt caching.** The system prompt + capability registry + few-shot
   examples are static → mark them `cache_control` on the Anthropic backend
   (already how `anthropic_backend` could work). Only `context` + `utterance`
   + `now` are uncached, ~50–150 tokens.
3. **Compact schema hint, not `model_json_schema()`** — reuse the lesson from
   `extract/schema.py` (`SCHEMA_JSON`, `_EXAMPLES` as `INPUT:/OUTPUT:` pairs,
   never fenced ```json). Applies double here because the combined schema is
   bigger.
4. **Context budget.** `format_context` already caps recent turns; keep it
   tight (last 3–4 turns, ~40 tokens each).
5. **Skip the model entirely** when a turn is obviously deterministic — a bare
   "yes"/"no" to a gate, an empty utterance, a slash-command-like action. Cheap
   pre-checks in the orchestrator before `decide`.

Expected: a store turn drops from ~2 calls / ~900 in+out tokens to ~1 call /
~450, most of it cached.

## Per-backend behaviour

`decide` is one combined prompt — small local models (`llama3.2:3b` on the
`light` profile) are brittle with big combined prompts (see
`model-backends.md`). So:

- **`anthropic` / `hybrid`** — one `decide` call (Haiku handles it fine).
- **`local` (`light`)** — keep the current two-step (`route` is a cheap one-
  word call; `extract` is the compact JSON call). `decide` is available but
  off by default on `light`.
- **`local` (`quality`)** — try `decide`; fall back to two-step on parse
  failure.

Config: `[backend] decide = "auto"` (`auto` = combined for cloud/quality,
split for light) | `"combined"` | `"split"`.

## Backend interface

`Backend` gains:

```python
def decide(self, utterance: str, *, context: str, now: datetime,
           capabilities: list[Capability]) -> Plan: ...
```

`LocalBackend.decide` for `split` mode just calls the existing `route` +
`extract` and assembles a one-step `Plan`. So the orchestrator only ever calls
`decide` — the split/combined choice is inside the backend. Clean seam.

## Orchestrator changes

`Orchestrator.handle`:

```
pre-checks (gate reply? empty? ) → deterministic
plan = backend.decide(text, context=history, now=now, capabilities=REGISTRY)
for step in plan.steps:
    store  → resolve → persist → gate  (as today, but extraction came from decide)
    query  → query_pipeline.answer(step.question)
    action → REGISTRY[step.action].handler(session, **step.args)
merge step results → one TurnResponse (or a gate if any store step gates)
```

Multi-step turns return combined `cards` + a phrased summary. A gate on any
store step pauses the whole turn (same `PendingStore` mechanism, extended to
hold the remaining steps).

## Phasing

1. **`Plan` / `Step` / `Capability` models + registry** with 3–4 safe actions.
   `decide` in `LocalBackend` as split-mode only (assembles a Plan from the
   existing calls). Orchestrator switches to consuming `Plan`. **No behaviour
   change, no new prompt** — pure refactor, fully covered by existing tests.
2. **Combined `decide` prompt** for the Anthropic backend + `prompts/
   decide.txt` + held-out fixtures (`tests/fixtures/decide_*.json`). Gate on
   `[backend].decide`.
3. **Multi-step turns** — orchestrator loop over `plan.steps`, combined
   response, gate-with-remaining-steps.
4. **Actions wired to real handlers** — `open_folder`, `show_photos`,
   `search_files`. UI renders the resulting cards / navigates.
5. **Prompt caching + local `quality` combined mode + eval pass** on the
   `utterances_*` fixtures; re-baseline pass-rate thresholds.

Phase 1 is a safe, test-covered refactor and worth doing regardless. Phases
2–5 are the actual feature and each needs its own eval baseline.

## Open questions for review

1. Is "action" broad enough, or do we also want the model to *compose* actions
   (call handler A, feed its output to handler B)? (Recommend: no — keep steps
   flat for v1.)
2. Should `decide` also return the `answer_shape` for query steps, or leave
   that to the existing planner? (Recommend: leave it — less schema.)
3. How much chat context is worth the tokens — last 3 turns? last 5? Tune with
   the eval set.
4. Do we expose `[backend].decide` to users or keep it internal/auto only?
