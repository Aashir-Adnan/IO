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

6. **HuggingFace model download** — only when `backend.embedder` is `"builtin"`
   (or `"auto"` and Ollama is unreachable) AND the fastembed model is not yet in
   `backend.models_dir`. A one-time GET of `nomic-ai/nomic-embed-text-v1.5`
   (~520 MB); nothing about the user is sent. Once cached, embedding is fully
   offline. `io doctor --fetch-embedder` triggers it deliberately.

7. **`git fetch` to the update remote** — `[updates].enabled` (default true):
   `io_assistant/updates/check.py` runs `git fetch <remote>` in IO's own
   checkout (on startup, then every `interval_h`) to see whether a newer commit
   exists. Plain git only: no GitHub API, no token stored by IO, no IO
   identifiers in the request, `GIT_TERMINAL_PROMPT=0`. It never applies
   anything on its own: an update runs only when the user clicks "Update &
   restart". `[updates] enabled = false` opens no socket.

8. **Google Drive (memory sync)** — `[sync].enabled` (default **false**) and signed
   in: `accounts.google.com` / `oauth2.googleapis.com` for sign-in, and
   `www.googleapis.com` (Drive v3, scope `drive.appdata` only — IO can reach its
   own hidden app folder and nothing else in the Drive) to exchange sync batches.
   What leaves the machine: people, places, items, occasions, records/tasks,
   affiliations, conversations and messages as gzip-JSON, in plaintext to the
   user's *own* Drive (Google encrypts at rest); embeddings and the file index
   never sync. The refresh token lives in the OS keychain; the password is never
   seen. `[sync] folder = "<dir>"` uses a local directory instead and opens no
   socket. `[sync] enabled = false` opens no socket.

9. **Open-Meteo (weather widget)** — `geocoding-api.open-meteo.com` and
   `api.open-meteo.com`, only while a weather widget on the home screen has a
   city set. The *service* makes the calls (never the browser): a place-name
   search, or coordinates for the forecast; nothing else about the user. No key.
   No weather widget ⇒ no socket.

10. **Gmail (Important widget)** — `gmail.googleapis.com` plus the Google sign-in
    hosts (case 8), only after the user clicks "Connect Gmail". Scope
    `gmail.readonly`, message *metadata* only (From/Subject/Date via
    `format=metadata`), never bodies. Its own keychain token, separate from the
    Drive sync grant, so neither consent widens the other. The service calls
    Google; sender + subject go to the local UI only. Disconnect clears the token.

11. **The phone app, over the user's own network** — `[service] remote_token`
    (empty by default; no change to anything when unset). When set, every route
    but `/health` requires `Authorization: Bearer <token>`, checked once in
    middleware before any route runs. The user also points `[service] host` at
    a reachable interface themselves (e.g. their Tailscale IP) — nothing here
    changes that default either. What this opens is reachability from the
    user's *own* second device, on a private network they control (Tailscale
    or equivalent), auth-gated — not a third party, and not the public
    internet. See `docs/superpowers/specs/2026-09-23-phone-app-design.md`.

`web.enabled = false` (the default) ⇒ the `web` action is not registered, the
routing pre-check is skipped, and general-knowledge questions stay `unknown`
exactly as before — no web tables are touched, no sockets opened.

The `LocalBackend` + `Embedder` socket guard (`tests/test_e2e_store.py`) still
enforces that the *local* provider path opens no foreign sockets. The Soniox
STT path is browser-side and provider-gated, so it does not affect that guard —
but it MUST stay behind the `stt_provider` + key check.
