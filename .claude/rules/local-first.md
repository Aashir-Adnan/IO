# Rule: local-first

IO runs entirely on the user's machine by default. Permitted non-local network
traffic is limited to these opt-in cases; everything else — telemetry,
analytics, CDN assets, bundled cloud calls, any other outbound connection to a
non-local host — is a bug.

1. **`api.anthropic.com`** — only when `backend.provider` is `"anthropic"` or
   `"hybrid"`. Credential from the environment (`ANTHROPIC_AUTH_TOKEN` /
   `ANTHROPIC_API_KEY`), never stored by IO.
2. **`api.soniox.com` + `stt-rt.soniox.com`** — real-time speech-to-text, only
   when `voice.stt_provider = "soniox"` AND `SONIOX_API_KEY` is set in the
   environment. IO's server makes exactly one call (`POST
   /v1/auth/temporary-api-key`) to mint a short-lived token; the browser then
   streams mic audio straight to `stt-rt.soniox.com` with that temp token. The
   real key never leaves the server. Missing key ⇒ silent fallback to local
   Whisper. Embeddings and the datastore stay local regardless.

3. **A self-hosted SearXNG** (`web.searxng_url`, default `http://localhost:8888`)
   — only when `web.enabled = true` AND `web.provider = "searxng"`. It runs in
   IO's own Docker stack, so the search query never reaches a third party; the
   port is local. This is barely an exception and needs no further gating.
4. **Result-page fetches** — when `web.enabled = true`, `web/fetch.py` makes
   plain `GET`s to the URLs SearXNG returned, to extract article text for a
   Tier-C answer. The hosts are whatever the search surfaced; no credentials,
   no IO identifiers, no `userEmail` in the request.
5. **A cloud search provider** (`web.provider` set to anything other than
   `"searxng"` / `"none"`) — a deliberate opt-in for users who won't run the
   container. Only the configured endpoint, only when `web.enabled = true`.
   Not implemented yet; the config only accepts `"searxng"` / `"none"` today.

`web.enabled = false` (the default) ⇒ the `web` action is not registered, the
routing pre-check is skipped, and general-knowledge questions stay `unknown`
exactly as before — no web tables are touched, no sockets opened.

The `LocalBackend` + `Embedder` socket guard (`tests/test_e2e_store.py`) still
enforces that the *local* provider path opens no foreign sockets. The Soniox
STT path is browser-side and provider-gated, so it does not affect that guard —
but it MUST stay behind the `stt_provider` + key check.
