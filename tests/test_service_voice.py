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

    def streamer(self):
        outer = self

        class Session:
            def __init__(self):
                self._fed = 0

            def feed(self, pcm):
                self._fed += len(pcm)

            def poll(self):
                return outer._t[: self._fed // 4] or None

            def finish(self):
                return outer._t

        class Engine:
            def session(self):
                return Session()

        return Engine()

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
def test_voice_transcribe_only_available_without_files_feature(config, fake_backend, db):
    # /voice/transcribe must not be gated behind [files].enabled — the ask-bar
    # mic and caption box rely on it.
    assert config.files.enabled is False
    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db),
        voice=FakeVoice(text="open downloads"))
    with TestClient(app) as c:
        r = c.post("/voice/transcribe",
                   files={"audio": ("a.wav", WAV.read_bytes(), "audio/wav")})
    assert r.status_code == 200
    assert r.json()["transcript"] == "open downloads"


@requires_db
def test_stt_mode_defaults_to_whisper(config, fake_backend, db):
    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db),
        voice=FakeVoice())
    with TestClient(app) as c:
        m = c.get("/voice/stt").json()
    assert m == {"provider": "whisper", "streaming": False}


@requires_db
def test_stt_mode_soniox_when_configured(config, fake_backend, db, monkeypatch):
    monkeypatch.setenv("SONIOX_API_KEY", "snx-real")
    config.voice.stt_provider = "soniox"
    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db),
        voice=FakeVoice())
    with TestClient(app) as c:
        m = c.get("/voice/stt").json()
        assert m == {"provider": "soniox", "streaming": True}

        # token mint proxies the real key -> a temporary one, key never returned raw
        import io_assistant.transcribe.soniox as sx

        def fake_post(url, headers, json, timeout):
            assert "Bearer snx-real" == headers["Authorization"]
            assert json["usage_type"] == "transcribe_websocket"
            class R:
                def raise_for_status(self): pass
                def json(self): return {"api_key": "snx_temp_x", "expires_at": "2026-01-01T00:00:00Z"}
            return R()
        monkeypatch.setattr(sx.httpx, "post", fake_post)
        tok = c.post("/voice/stream-token").json()
    assert tok["api_key"] == "snx_temp_x"
    assert tok["model"] == "stt-rt-v5"
    assert tok["websocket_url"].startswith("wss://stt-rt.soniox.com")


@requires_db
def test_stt_mode_whisper_stream(config, fake_backend, db):
    config.voice.stt_provider = "whisper-stream"
    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db),
        voice=FakeVoice())
    with TestClient(app) as c:
        assert c.get("/voice/stt").json() == {"provider": "whisper-stream", "streaming": True}


@requires_db
def test_ws_transcribe_streams_final(config, fake_backend, db):
    config.voice.stt_provider = "whisper-stream"
    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db),
        voice=FakeVoice(text="move away on the tenth"))
    with TestClient(app) as c, c.websocket_connect("/ws/transcribe") as ws:
        ws.send_bytes(b"\x00\x01" * 8000)
        ws.send_text('{"type":"end"}')
        got_final = None
        for _ in range(30):
            msg = ws.receive_json()
            if msg["type"] == "final":
                got_final = msg["text"]
                break
        assert got_final == "move away on the tenth"


@requires_db
def test_stream_token_503_without_key(config, fake_backend, db, monkeypatch):
    monkeypatch.delenv("SONIOX_API_KEY", raising=False)
    config.voice.stt_provider = "soniox"
    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db),
        voice=FakeVoice())
    with TestClient(app) as c:
        r = c.post("/voice/stream-token")
    assert r.status_code == 503


@requires_db
def test_voice_health(config, fake_backend, db):
    app = create_app(config, orchestrator=Orchestrator(
        config, session_factory=lambda: db, backend=fake_backend),
        engine=db.get_bind(), conversations=ConversationStore(lambda: db),
        voice=FakeVoice())
    with TestClient(app) as c:
        h = c.get("/voice/health").json()
    assert h["whisper"] is True and "voice" in h
