import os

import pytest

from io_assistant.speak.interface import Speaker, SpeakError
from io_assistant.speak.piper import PiperSpeaker


def test_fake_speaker_satisfies_protocol(fake_speaker):
    assert isinstance(fake_speaker, Speaker)


def test_piper_missing_voice_raises(config, tmp_path):
    config.voice.voices_dir = str(tmp_path)  # empty -> no voice file
    with pytest.raises(SpeakError, match="voice not found"):
        PiperSpeaker(config).synthesize("hello")


@pytest.mark.voice
@pytest.mark.skipif(os.environ.get("IO_VOICE_TESTS") != "1", reason="opt-in")
def test_piper_real_synthesis(config):
    data = PiperSpeaker(config).synthesize("Hello from eye oh.")
    assert data[:4] == b"RIFF" and len(data) > 1000
