import base64
from pathlib import Path

from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.orchestrator import Orchestrator
from io_assistant.conversation.store import ConversationStore
from io_assistant.service.app import create_app
from io_assistant.db import models as m

WAV = Path(__file__).parent / "fixtures" / "audio" / "hello.wav"


class FakeVoice:
    def __init__(self, text="buy milk"):
        self._t = text

    def transcriber(self):
        outer = self

        class T:
            def transcribe(self, p):
                from io_assistant.transcribe.interface import Transcript
                return Transcript(text=outer._t, confidence=0.9)

        return T()

    def speaker(self):
        class S:
            def synthesize(self, text):
                return b"RIFF0000WAVEfmt "

        return S()

    def health(self):
        return {"whisper": True, "piper": True, "voice": "test", "reason": None}


def _stub(monkeypatch):
    import io_assistant.orchestrator as orch
    monkeypatch.setattr(orch, "Embedder", lambda cfg: type("E", (), {
        "embed_one": lambda self, t: [0.0] * 768,
        "embed": lambda self, ts: [[0.0] * 768 for _ in ts]})())


@requires_db
def test_voice_turn_transcribes_answers_and_speaks(config, fake_backend, db, monkeypatch):
    _stub(monkeypatch)
    fake_backend.set_intent("store")
    fake_backend.set_ack("Noted.")
    from io_assistant.models_domain import ExtractionResult, ExtractedRecord
    fake_backend.set_extraction(ExtractionResult(records=[
        ExtractedRecord(kind="note", title="buy milk", confidence=0.9)]))
    o = Orchestrator(config, session_factory=lambda: db, backend=fake_backend)
    app = create_app(config, orchestrator=o, engine=db.get_bind(),
                     conversations=ConversationStore(lambda: db), voice=FakeVoice())
    with TestClient(app) as c:
        r = c.post("/voice",
                   files={"audio": ("a.wav", WAV.read_bytes(), "audio/wav")},
                   data={"speak": "1"})
    body = r.json()
    assert r.status_code == 200
    assert body["transcript"] == "buy milk"
    assert body["kind"] == "ack" and body["text"] == "Noted."
    assert base64.b64decode(body["audio_b64"])[:4] == b"RIFF"
    assert db.query(m.Message).filter_by(source="voice").count() == 2


@requires_db
def test_voice_health(config, fake_backend, db):
    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db),
        voice=FakeVoice())
    with TestClient(app) as c:
        h = c.get("/voice/health").json()
    assert h["whisper"] is True and "voice" in h
