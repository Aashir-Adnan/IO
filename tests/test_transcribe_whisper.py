import os

import pytest

from io_assistant.transcribe.interface import Transcriber, Transcript


def test_fake_transcriber_satisfies_protocol(fake_transcriber):
    assert isinstance(fake_transcriber, Transcriber)


def test_fake_transcriber_returns_configured(fake_transcriber):
    fake_transcriber.set_text("buy milk")
    fake_transcriber.set_confidence(0.9)
    t = fake_transcriber.transcribe("ignored.wav")
    assert isinstance(t, Transcript)
    assert t.text == "buy milk" and t.confidence == 0.9


@pytest.mark.voice
@pytest.mark.skipif(os.environ.get("IO_VOICE_TESTS") != "1", reason="opt-in")
def test_whisper_real_transcription(config):
    from pathlib import Path

    from io_assistant.transcribe.whisper import WhisperTranscriber

    # A 220 Hz tone, not speech — this only checks the pipeline returns a
    # Transcript without error. Swap in a real "hello" clip for accuracy checks.
    wav = Path(__file__).parent / "fixtures" / "audio" / "hello.wav"
    t = WhisperTranscriber(config).transcribe(str(wav))
    assert isinstance(t.text, str)
