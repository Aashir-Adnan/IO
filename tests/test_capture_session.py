import pytest

from io_assistant.capture.session import build_utterance
from io_assistant.service.schemas import UtteranceIn


def test_build_utterance():
    u = build_utterance("  buy milk \n", 0.8)
    assert isinstance(u, UtteranceIn)
    assert u.text == "buy milk" and u.source == "voice"


def test_build_utterance_rejects_empty():
    with pytest.raises(ValueError):
        build_utterance("   ", None)
