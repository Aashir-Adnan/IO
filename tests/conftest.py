import os
from datetime import datetime
from pathlib import Path

import pytest

from io_assistant.models_domain import AnswerShape, ExtractionResult, Intent

from io_assistant.config import (
    Config, BackendConfig, ResolverConfig, ServiceConfig, VoiceConfig, CaptureConfig,
    UiConfig,
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

    def set_ack(self, s: str):
        self._ack = s

    def route(self, utterance: str, *, context: str | None = None) -> Intent:
        self._ctx(context)
        self.calls.append("route")
        return self._intent

    def extract(self, utterance: str, now: datetime) -> ExtractionResult:
        self.calls.append("extract")
        return self._extraction

    def plan(self, question: str, now: datetime, *, context: str | None = None) -> dict:
        self._ctx(context)
        self.calls.append("plan")
        return self._plan

    def phrase(self, question, rows, shape, *, context: str | None = None) -> str:
        self._ctx(context)
        self.calls.append("phrase")
        return self._answer

    def acknowledge(self, facts: str, *, context: str | None = None) -> str:
        self._ctx(context)
        self.calls.append("acknowledge")
        return self._ack


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
