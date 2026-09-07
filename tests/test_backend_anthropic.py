import datetime as dt
import pytest
from io_assistant.backend.anthropic_backend import AnthropicBackend
from io_assistant.backend.interface import BackendParseError


class FakeBlock:
    def __init__(self, text):
        self.text = text
        self.type = "text"


class FakeMsg:
    def __init__(self, text):
        self.content = [FakeBlock(text)]


class FakeMessages:
    def __init__(self, text):
        self._text = text
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return FakeMsg(self._text)


class FakeClient:
    def __init__(self, text):
        self.messages = FakeMessages(text)


def test_route_maps_intent(config):
    c = FakeClient("QUERY")
    assert AnthropicBackend(config, client=c).route("what did I eat") == "query"
    assert c.messages.last_kwargs["model"] == "claude-haiku-4-5"


def test_extract_parses(config):
    payload = ('{"people":[],"places":[{"name":"Arcadian","aliases":[],"confidence":0.8}],'
               '"items":[],"occasions":[],"records":[]}')
    c = FakeClient(payload)
    r = AnthropicBackend(config, client=c).extract("ate at Arcadian", dt.datetime.now(dt.timezone.utc))
    assert r.places[0].name == "Arcadian"


def test_extract_bad_json_raises(config):
    with pytest.raises(BackendParseError):
        AnthropicBackend(config, client=FakeClient("sorry, no")).extract(
            "x", dt.datetime.now(dt.timezone.utc))
