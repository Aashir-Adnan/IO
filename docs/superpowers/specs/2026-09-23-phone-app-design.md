# Phone app (Flutter, Android first)

Date: 2026-09-23 · Status: approved

## Goal

IO runs entirely on a phone: no desktop required, own on-device memory, synced
to/from desktop via F's Drive protocol. Chat (store + query), a tasks list, and
"act like ChatGPT" web answers proxied through the user's own desktop when one
is reachable. Standalone sub-project; its own repo area (`phone/`), own release
cycle.

## Decisions (from brainstorming)

- **Flutter**, not React Native: one Dart codebase, strong offline/SQLite story,
  Anthropic is plain HTTP so no SDK gap.
- **Android first.** iOS needs the $99/yr Apple Developer Program for a lasting
  install (7-day sideload expiry otherwise); revisit later. The Dart code is the
  same for both, so nothing here is Android-specific except packaging.
- **No on-device embedder.** Entity resolution and retrieval run in the same
  lexical-fallback mode A already built for when Ollama is unreachable: exact
  match, then fuzzy, no vectors. Vectors are backfilled on desktop when a
  phone-created row syncs there (existing `EmbeddingBackfiller`).
- **The LLM boundary is unchanged** (rules/llm-boundaries.md): the phone calls
  Anthropic for route/extract/plan/phrase only. Dates, SQL-equivalent queries,
  and entity identity are deterministic Dart, ported from the Python originals,
  never delegated to the model.
- **A (embedder order) is unchanged.** No code changes to the desktop embedder
  chain from this spec.
- **Web answers**: proxied through the user's own desktop IO service over their
  own network (e.g. Tailscale), not a hosted SearXNG. Desktop gets a minimal,
  opt-in, token-gated remote-access mode (below). No home server configured ⇒
  no web answers on the phone, same as `web.enabled = false` today.
- **API key on-device.** The Anthropic key lives in Android Keystore
  (`flutter_secure_storage`), entered once in onboarding. This amends "a
  credential is never stored by IO" specifically for this client: the phone
  *is* the device the user is authorizing, there is no separate IO process to
  keep it out of.

## Design

### 1. Desktop: opt-in remote access (small, in this repo)

- `ServiceConfig.remote_token: str = ""`. Empty (default) ⇒ no behavior change
  at all — every existing test and the whole local-first posture holds exactly
  as today.
- When non-empty, a FastAPI dependency checks `Authorization: Bearer <token>`
  on every route except `/health`; a mismatch or missing header is 401. Applied
  once, not per-endpoint, so nothing can be added later and forget the check.
- The user points `[service] host` at their Tailscale IP themselves (already
  configurable; no new setting) — Tailscale is a private device-to-device
  network the user controls, not public exposure.
- `local-first.md` gets a new case: "opens a socket beyond loopback only when
  `remote_token` is set; auth-gated; the far end is the user's own second
  device on their own VPN, not a third party."
- Nothing else about the desktop app changes: this is purely "can be reached
  by another device I own, if I choose to open that door."

### 2. Phone data model

SQLite (`sqflite`/`drift`) mirrors the synced subset of the Postgres schema:
`people, places, items, occasions, records, collections, conversations,
messages` plus the five link tables, each with `sync_id, synced_at,
updated_at, created_at` exactly matching migration 0010's shape — same field
names, same semantics ("dirty" = `synced_at IS NULL OR updated_at >
synced_at"). No `embedding` column anywhere. `sync_tombstones`, `sync_aliases`,
`sync_state` mirror `io_assistant/db/models.py`'s bookkeeping tables.

### 3. Ports from Python to Dart (deterministic, no model)

- `resolve/dates.py` → date grounding ("tomorrow", "the 10th of September",
  someday-phrases). Direct port; same test fixtures translated to Dart tests.
- `resolve/resolver.py` → exact + fuzzy only (drop the vector branch; this *is*
  the lexical-fallback path, not a new mode). A Dart token-set-ratio fuzzy
  match (package `fuzzywuzzy` or a small hand-rolled equivalent) replaces
  `rapidfuzz`.
- `persist/writer.py` → the store pipeline: create/resolve entities, write the
  record + links, apply default-today/roll-forward for bare tasks.
- `query/compile.py` + `retrieve.py` → the query pipeline, minus the semantic
  branch (never present, no embeddings) — structured SQLite queries only, same
  time-window and aggregation-count handling.
- `query/respond.py` → `rows_to_json`, `_due_label`, `overdue` — identical
  logic, feeds the phrasing call.
- `tasks/complete.py` → `close_record` matching for "mark X done" turns.
- `orchestrator._web_precheck` → the regex gate (news/fact/track/first-person
  guard) that decides whether a query might warrant a web answer.
- `sync/codec.py` + `sync/engine.py` (push/pull/snapshot/merge rules) → the
  wire format is already plain JSON with `sync_id`-keyed foreign keys, so this
  ports without protocol changes. Conformance: both implementations run against
  the same JSON fixture files (checked into this repo, read by both the
  Python and Dart test suites) — a batch in, expected merged state out.

### 4. LLM calls

Combined decide (route+extract+plan in one call, matching `[backend] decide =
"combined"`) using the same prompt files, vendored as Flutter assets and kept
in sync by a script that diffs against `io_assistant/prompts/*.txt` and fails
CI if they drift. One Anthropic call per turn for decide, one for phrasing,
same as desktop's `AnthropicBackend`.

### 5. Web answers

If a home server URL + token are set in Settings: on a query-shaped turn where
local retrieval comes up empty or `_web_precheck` fires, the phone calls
`GET <home>/web?q=&kind=` with the bearer token and shows the returned answer +
sources. No server configured, or the call fails (desktop off, no network path):
falls back to the local "I don't know" behavior, never a hard error.

### 6. Onboarding

1. Enter/paste Anthropic API key (validated with one cheap call).
2. Sign in with Google (Drive `appdata` scope — same OAuth client as desktop's
   `[sync]`, a public "Desktop app"-type client's ID works for installed apps
   generally, but Google requires a separate Android OAuth client id per app
   signing certificate; this is a packaging detail resolved in the plan, not a
   design fork).
3. Optional: home server URL + token, for web answers.
4. First sync (may be a large one-time pull if desktop already has data).

### 7. MVP screens

Chat (store/query, typed only), Tasks (list + tick-to-complete, mirrors the
desktop widget's grouping), Settings (API key, account, home server, sync
status). No files, no widgets, no voice.

## Testing

Dart unit tests for every ported module (dates, resolver, persist, query,
respond, web-precheck) mirroring the existing Python test cases one-for-one
where the logic is identical. Sync engine: the same JSON conformance fixtures
Python's suite reads, run against the Dart implementation, plus Dart-side
integration tests against an in-memory/temp SQLite (never mocked, same
principle as `rules/test-discipline.md`). The desktop remote-token gate is
tested with FastAPI's `TestClient` (no real network). Anthropic calls and the
Google OAuth flow are faked in tests via injected clients; nothing live in the
suite. Live verification (a real phone or emulator, a real Anthropic key, a
real Drive account) happens by hand, the same way voice and Ollama-dependent
features are verified in this repo today.

## Out of scope

Files, media, widgets, voice, web-answer caching on-device, iOS packaging, an
in-app onboarding wizard beyond the four steps above, publishing to Google
Play (sideloaded APK only for now).

## Risks

- Porting five Python modules to Dart by hand risks behavioral drift; the
  shared-fixture approach (dates, sync conformance) is the main guard, but
  resolver/query don't have an equivalent shared-fixture harness yet — plan
  should add one (translate the existing pytest cases into a fixture format
  both suites can read, where practical).
- Google's per-app-signing-certificate OAuth client requirement (Android) is a
  packaging detail that could turn out to need more than one client id
  (debug vs. release signing) — resolved when the plan reaches that task, not
  a design blocker.
- Tailscale (or equivalent) setup is manual and outside this repo's control;
  the desktop change only provides the auth gate, not the tunnel itself.
