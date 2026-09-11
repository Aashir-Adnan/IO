import os
import threading
from datetime import datetime
from pathlib import Path

import pytest

from io_assistant.models_domain import AnswerShape, ExtractionResult, Intent

from io_assistant.config import (
    Config, BackendConfig, ResolverConfig, ServiceConfig, VoiceConfig, CaptureConfig,
    UiConfig, FilesConfig,
)
from io_assistant.db.base import make_engine, make_session_factory, Base
from io_assistant.db import models  # noqa: F401 — register mappers
from sqlalchemy import text


@pytest.fixture
def config() -> Config:
    return Config(
        database_url="postgresql+psycopg://io:io@localhost:5432/io_test",
        embedding_dim=768,
        backend=BackendConfig(
            provider="local", profile="light",
            anthropic_model="claude-haiku-4-5",
            ollama_url="http://localhost:11434", ollama_keep_alive="30s",
            instruct_model="llama3.2:3b", embed_model="nomic-embed-text",
            num_thread=0,
        ),
        resolver=ResolverConfig(
            fuzzy_threshold=92, vector_similarity_threshold=0.85,
            confidence_gate_threshold=0.6,
        ),
        service=ServiceConfig(),
        voice=VoiceConfig(),
        capture=CaptureConfig(),
        ui=UiConfig(),
        files=FilesConfig(),
    )


TEST_DB_URL = os.environ.get("IO_TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not TEST_DB_URL, reason="IO_TEST_DATABASE_URL not set")


def _alembic_config():
    """Alembic config pointed at the TEST database, with absolute paths so it
    works regardless of the pytest working directory."""
    from alembic.config import Config as AlembicConfig

    root = Path(__file__).resolve().parents[1]
    cfg = AlembicConfig(str(root / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(root / "io_assistant" / "db" / "migrations")
    )
    # migrations/env.py honours an explicitly-set sqlalchemy.url first.
    cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    return cfg


@pytest.fixture(scope="session")
def engine():
    """Test schema is built by the real Alembic migration, not create_all —
    so the migration DDL (indexes, HNSW, NOT NULL defaults) is exercised."""
    if not TEST_DB_URL:
        pytest.skip("IO_TEST_DATABASE_URL not set")
    from alembic import command

    eng = make_engine(TEST_DB_URL)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        # Leftovers from an older create_all-built schema would collide with
        # the migration's CREATE TABLEs; start from a known-empty database.
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    Base.metadata.drop_all(eng)

    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    yield eng
    command.downgrade(cfg, "base")


@pytest.fixture
def db(engine):
    """Function-scoped session wrapped in a rolled-back transaction."""
    connection = engine.connect()
    trans = connection.begin()
    Session = make_session_factory(connection)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        connection.close()


class FakeBackend:
    def __init__(self):
        self._intent: Intent = "unknown"
        self._extraction = ExtractionResult()
        self._plan: dict = {}
        self._answer = ""
        self._ack = ""
        self._file_summary = {"summary": "", "names": [], "references": []}
        self._file_answer = ""
        self.last_files = None
        self.last_summarize = None
        self.calls: list[str] = []
        self.last_context: str | None = None

    def _ctx(self, c):
        if c:
            self.last_context = c

    def set_intent(self, i: Intent):
        self._intent = i

    def set_extraction(self, r: ExtractionResult):
        self._extraction = r

    def set_answer(self, s: str):
        self._answer = s

    def set_plan(self, d: dict):
        self._plan = d

    def set_decide(self, plan):
        """plan: a models_domain.Plan (enables combined-mode `decide`)."""
        self._decide_plan = plan

    def decide(self, utterance, now, *, context=None, files_enabled=False, web_enabled=False):
        self._ctx(context)
        self.calls.append("decide")
        plan = getattr(self, "_decide_plan", None)
        if plan is None:
            from io_assistant.backend.interface import BackendParseError
            raise BackendParseError("no decide plan set on FakeBackend")
        return plan

    def set_ack(self, s: str):
        self._ack = s

    def route(self, utterance: str, *, context: str | None = None) -> Intent:
        self._ctx(context)
        self.calls.append("route")
        return self._intent

    def extract(self, utterance: str, now: datetime, *, context: str | None = None) -> ExtractionResult:
        self._ctx(context)
        self.calls.append("extract")
        return self._extraction

    def plan(self, question: str, now: datetime, *, context: str | None = None) -> dict:
        self._ctx(context)
        self.calls.append("plan")
        return self._plan

    def phrase(self, question, rows, shape, *, context: str | None = None) -> str:
        self._ctx(context)
        self.calls.append("phrase")
        self.last_phrase_rows = rows
        return self._answer

    def acknowledge(self, facts: str, *, context: str | None = None) -> str:
        self._ctx(context)
        self.calls.append("acknowledge")
        return self._ack

    def set_file_summary(self, d):
        self._file_summary = d

    def set_file_answer(self, s):
        self._file_answer = s

    def summarize_file(self, title, head_text, *, mime=None):
        self.calls.append("summarize_file")
        self.last_summarize = (title, head_text)
        return self._file_summary

    def answer_from_files(self, question, files, shape, *, context=None):
        self._ctx(context)
        self.calls.append("answer_from_files")
        self.last_files = files
        return self._file_answer


@pytest.fixture
def fake_backend():
    return FakeBackend()


class FakeSpeaker:
    def __init__(self):
        self.said: list[str] = []
        self.synth_calls: list[str] = []

    def say(self, text: str) -> None:
        self.said.append(text)

    def synthesize(self, text: str) -> bytes:
        self.synth_calls.append(text)
        return b"RIFF\x00\x00\x00\x00WAVEfmt "


@pytest.fixture
def fake_speaker():
    return FakeSpeaker()


class FakeTranscriber:
    def __init__(self):
        self._text = ""
        self._conf = None
        self.calls: list[str] = []

    def set_text(self, s):
        self._text = s

    def set_confidence(self, c):
        self._conf = c

    def transcribe(self, wav_path: str):
        from io_assistant.transcribe.interface import Transcript

        self.calls.append(wav_path)
        return Transcript(text=self._text, confidence=self._conf)


@pytest.fixture
def fake_transcriber():
    return FakeTranscriber()


class StubEmbedder:
    """Deterministic embedder for tests — 768-d zeros unless a mapping hit."""

    def __init__(self, mapping: dict | None = None):
        self.mapping = mapping or {}
        self.calls: list[str] = []

    def embed_one(self, t: str) -> list[float]:
        self.calls.append(t)
        return self.mapping.get(t, [0.0] * 768)

    def embed(self, ts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in ts]


@pytest.fixture
def stub_embedder():
    return StubEmbedder()


# --------------------------------------------------------------------------- #
# ui_page — opt-in Playwright DOM smoke (IO_UI_TESTS=1)
# --------------------------------------------------------------------------- #

_UI_ROOT = Path(__file__).resolve().parent.parent / "frontend"
_UI_FIX = Path(__file__).resolve().parent / "fixtures" / "ui"


def _ui_fixture(name: str):
    import json as _json

    return _json.loads((_UI_FIX / name).read_text())


def _make_ui_server():
    import json as _json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    canned_get = {
        "/standby": lambda: _ui_fixture("standby.json"),
        "/voice/health": lambda: _ui_fixture("voice_health.json"),
        "/conversations": lambda: _ui_fixture("conversations.json"),
        "/conversation": lambda: _ui_fixture("conversation.json"),
        "/health": lambda: {"ok": True, "database": True, "backend_provider": "fake"},
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # silence
            pass

        def _send_json(self, obj, status=200):
            body = _json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in canned_get:
                return self._send_json(canned_get[path]())
            if path.startswith("/entity/"):
                return self._send_json(
                    {"etype": "person", "id": 1, "name": "Nafay",
                     "subtitle": "FRIEND · 3 NOTES", "confidence": 0.82, "facts": []}
                )
            rel = path.lstrip("/") or "index.html"
            if path in ("/", "/app", "/app/"):
                rel = "index.html"
            fp = (_UI_ROOT / rel).resolve()
            if not str(fp).startswith(str(_UI_ROOT.resolve())) or not fp.is_file():
                self.send_response(404)
                self.end_headers()
                return
            ctype = {
                ".js": "text/javascript", ".css": "text/css",
                ".html": "text/html", ".woff2": "font/woff2",
                ".json": "application/json",
            }.get(fp.suffix, "application/octet-stream")
            data = fp.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            if path == "/conversation":
                return self._send_json({"conversation_id": 99})
            if path == "/utterance":
                return self._send_json(_ui_fixture("turn_answer.json"))
            if path == "/voice":
                out = dict(_ui_fixture("turn_answer.json"))
                out.update(transcript="how long at granjur", transcript_confidence=0.9)
                return self._send_json(out)
            self._send_json({}, status=404)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture
def ui_page():
    if os.environ.get("IO_UI_TESTS") != "1":
        pytest.skip("UI smoke is opt-in: set IO_UI_TESTS=1")
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        pytest.skip("playwright not installed (uv add --group dev playwright)")

    srv, base = _make_ui_server()
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch()
    except Exception as e:  # chromium not installed
        pw.stop()
        srv.shutdown()
        pytest.skip(f"chromium unavailable: {e} — run `uv run playwright install chromium`")

    ctx = browser.new_context(permissions=["microphone"])
    page = ctx.new_page()

    class UiPage:
        def __init__(self):
            self.page = page
            self.base = base

        def open(self):
            page.goto(f"{base}/app/")
            page.wait_for_function("window.__ctx !== undefined")
            return self

        def goto_view(self, name):
            page.evaluate("v => window.__ctx.store.set({ view: v })", name)
            page.wait_for_timeout(50)

        def send(self, text):
            page.evaluate("t => window.__ctx.store.get()", None)

        def eval(self, js, *arg):
            return page.evaluate(js, *arg) if arg else page.evaluate(js)

        def wait_for(self, selector, **kw):
            page.wait_for_selector(selector, **kw)

    up = UiPage()
    try:
        yield up
    finally:
        ctx.close()
        browser.close()
        pw.stop()
        srv.shutdown()
