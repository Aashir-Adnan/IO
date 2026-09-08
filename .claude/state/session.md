# Current session

**Phase 2 (files 2A + media 2C + packaging 2B) merged to `main`** and pushed
(`origin/main` = `41aaaa9`).

**Phase 2B.1 (full-featured bundle) + UI shell polish** — on branch
**`io-ui-shell-polish`** (from `io-phase-2b1-full-bundle` off `main`; NOT
merged). Full suite **302 pass / 10 skip**.

### 2B.1 — full bundle
- `packaging/io.spec` bundles **voice** (`collect_all` piper/faster_whisper/
  sounddevice/ctranslate2/onnxruntime/av; `packaging/hooks/hook-webrtcvad.py`
  overrides the broken contrib hook; `torch` excluded). Voice **models** still
  download on first use — `VoiceModels._ensure_voice_model` fetches the Piper
  `.onnx` on first `/voice` synth.
- `io_assistant/service/bootstrap.py` — `ensure_database(config)`: ping DB →
  `docker compose -p io -f <bundle>/docker-compose.yml up -d db` if down → wait →
  `alembic upgrade head`. `cli.run()`/`serve()` call it; `runner.error_dialog`
  shows `BootstrapError` in a pywebview window. Bundle ships `docker-compose.yml`
  + `scripts/initdb/`. **Prereq: Docker Desktop running.**
- **Verified locally**: `dist/IO/IO.exe` (~25 MB / ~350 MB) starts its own DB
  container, migrates, serves `/health`+`/voice/health`+`/standby`; 2nd launch
  → browser + exit (single-instance).

### UI shell polish
- Removed the white titlebar; `#status` → bottom of rail.
- Collapsible rail (216↔66 px, `localStorage["io.rail.collapsed"]`), icon+label,
  `IO` wordmark, chevron toggle.
- Standby: big centred iPhone-style clock + long date, then greeting/orb/stats/
  chips/composer, centre-aligned.
- **Orb fixed** — `orb.js` mounts its own fixed-size `.orb` div inside the host
  (was restyling the host → ellipse); layers centre via `inset:0;margin:auto`.
- `[hidden]{display:none!important}` (the drawer was still 240 px wide when hidden).
- Native folder picker: `runner.open_window` `js_api.pick_folder()` →
  `window.create_file_dialog(FOLDER_DIALOG)`; Files view "Choose folder…" button.
- Static assets served `Cache-Control: no-store` (`_NoCacheStatic`).

**Next:**
1. Final rebuild (`dev.ps1 build`) + `dev.ps1 install` → Desktop shortcut; a
   real fullscreen runtime check.
2. Merge `io-ui-shell-polish` → `main`.
3. Open-source readiness (on hold): default `provider = "local"`, verify local
   backend end-to-end, LICENSE, README, CI, make repo public.

Tests: `IO_TEST_DATABASE_URL='postgresql+psycopg://io:io@localhost:5432/io_test'
uv run pytest -q -p no:warnings`.
