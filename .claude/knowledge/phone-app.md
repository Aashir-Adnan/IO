# Phone app (`phone/`, Flutter, Android first)

Standalone: on-device SQLite, calls Anthropic directly (key in the platform
keystore), no desktop needed. Spec: `docs/superpowers/specs/2026-09-23-phone-app-design.md`.
Dart ports mirror the Python modules 1:1 and tests mirror pytest cases.

## Layout
- `lib/core/` — `db`, `dates`, `resolver`, `extraction`, `persist`, `query`, `plan`,
  `llm` (Anthropic decide/plan/phrase/acknowledge), `orchestrator` (one chat turn),
  `tasks`, `chat_store`, `secure_store`, `web` + `home_server` (see below).
- `lib/sync/` — `codec`, `engine`, `store`, `drive_store`, `auth`, `sync_manager`.
  Same wire protocol as `io_assistant/sync/`; proven by shared fixtures
  (`tests/test_sync_interop.py` ↔ `phone/test/sync/interop_test.dart`; regenerate
  with `IO_REGEN_FIXTURES=1`).
- `lib/features/` — onboarding (API key), chat, tasks, settings (key, sync, home server).
- `assets/prompts/*.txt` are copies of the desktop prompts; `tool/sync_prompts.py`
  regenerates them and `tests/test_phone_prompts_in_sync.py` guards drift.

## LLM boundary
Same as desktop (`rules/llm-boundaries.md`): the model routes/extracts/plans/phrases;
dates, entity identity, retrieval and gating are Dart.

## Web answers (memory first)
`webIntent()` (port of the desktop precheck) fires only for non-personal news/fact
questions or an explicit "search the web for X / google X / look up X" at the start
of the message. It calls the user's own desktop `GET /web?q=&kind=` with the bearer
token. Never auto-searches for what memory can answer; an empty memory answer only
*hints* at the explicit phrase. Explicit ask without a configured home server → a
"set your home server" message. Failures become readable errors.

Desktop setup: `[service] host` = Tailscale IP, `[service] remote_token` = secret,
`[web] enabled = true`. Phone: Settings → Home server (address + token → Test).

## Google sign-in / Drive sync (needs the user's Google Cloud project)
Scope `drive.appdata` only. Create an OAuth *Android* client (package + signing SHA-1)
and a *Web* client; build with `--dart-define=GOOGLE_SERVER_CLIENT_ID=<web client id>`.
Without it `GoogleAuthProvider.configured` is false and Settings says so. Details of the
desktop side: `knowledge/memory-sync.md`.

## Build / test
`flutter analyze`, `flutter test` (all tests use sqflite_common_ffi, no device).
SDK: `C:\Users\adnan\dev\android-sdk`, JDK 17 `C:\Program Files\Eclipse Adoptium\jdk-17.0.18.8-hotspot`.
`flutter build apk --debug` needs both (`JAVA_HOME`, `flutter config --android-sdk`).

## Not verified
Real device run, real Anthropic call from the phone, real Google sign-in/Drive.
