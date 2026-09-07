import os
from datetime import datetime

import pytest

from io_assistant.models_domain import AnswerShape, ExtractionResult, Intent

from io_assistant.config import Config, BackendConfig, ResolverConfig
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
    )


TEST_DB_URL = os.environ.get("IO_TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(not TEST_DB_URL, reason="IO_TEST_DATABASE_URL not set")


@pytest.fixture(scope="session")
def engine():
    if not TEST_DB_URL:
        pytest.skip("IO_TEST_DATABASE_URL not set")
    eng = make_engine(TEST_DB_URL)
    with eng.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


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
        self._answer = ""
        self.calls: list[str] = []

    def set_intent(self, i: Intent):
        self._intent = i

    def set_extraction(self, r: ExtractionResult):
        self._extraction = r

    def set_answer(self, s: str):
        self._answer = s

    def route(self, utterance: str) -> Intent:
        self.calls.append("route")
        return self._intent

    def extract(self, utterance: str, now: datetime) -> ExtractionResult:
        self.calls.append("extract")
        return self._extraction

    def plan(self, question: str, now: datetime) -> dict:
        self.calls.append("plan")
        return {}

    def phrase(self, question: str, rows: list[dict], shape: AnswerShape) -> str:
        self.calls.append("phrase")
        return self._answer


@pytest.fixture
def fake_backend():
    return FakeBackend()
