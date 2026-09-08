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


def test_make_client_uses_oauth_token_when_no_api_key(monkeypatch):
    import sys
    import io_assistant.backend.anthropic_backend as mod

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "oauth-abc")
    seen = {}

    class FakeAnthropic:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setitem(sys.modules, "anthropic", type("m", (), {"Anthropic": FakeAnthropic}))
    mod._make_client()
    assert seen["auth_token"] == "oauth-abc"
    assert seen["default_headers"]["anthropic-beta"] == "oauth-2025-04-20"


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


def test_route_uses_small_max_tokens(config):
    c = FakeClient("STORE")
    AnthropicBackend(config, client=c).route("remember milk")
    assert c.messages.last_kwargs["max_tokens"] <= 32


def test_extract_caches_stable_prefix(config):
    c = FakeClient('{"people":[],"places":[],"items":[],"occasions":[],"records":[]}')
    AnthropicBackend(config, client=c).extract(
        "ate at Arcadian", dt.datetime.now(dt.timezone.utc))
    kw = c.messages.last_kwargs
    # schema + few-shot travel in a cached system block, not re-sent per call
    system = kw["system"]
    assert isinstance(system, list)
    assert any(b.get("cache_control") for b in system)
    sys_text = " ".join(b.get("text", "") for b in system)
    assert "EXACTLY these keys" in sys_text  # SCHEMA_JSON
    user = kw["messages"][0]["content"]
    assert "Arcadian" in user and "EXACTLY these keys" not in user


def test_extract_bad_json_raises(config):
    with pytest.raises(BackendParseError):
        AnthropicBackend(config, client=FakeClient("sorry, no")).extract(
            "x", dt.datetime.now(dt.timezone.utc))
