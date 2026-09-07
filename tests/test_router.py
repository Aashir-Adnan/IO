import os
import json
from pathlib import Path
import pytest
from io_assistant.route.router import Router
from io_assistant.backend.local import LocalBackend


class B:
    """Stub backend for testing."""
    def __init__(self, intent):
        self.intent = intent
        self.called = False

    def route(self, u):
        self.called = True
        return self.intent

    def extract(self, *a):
        ...

    def plan(self, *a):
        ...

    def phrase(self, *a):
        ...


def test_delegates_to_backend():
    """Router should delegate to backend when utterance is non-empty."""
    b = B("store")
    assert Router(b).classify("I ate lunch with Ali") == "store"
    assert b.called


def test_empty_utterance_is_unknown_without_model_call():
    """Router should return 'unknown' for empty/whitespace utterances without calling backend."""
    b = B("store")
    assert Router(b).classify("   ") == "unknown"
    assert not b.called


@pytest.mark.ollama
def test_router_with_local_backend(config):
    """Test Router with LocalBackend on real utterances.

    Asserts >=80% intent match on utterances_route.json fixture.
    Skipped by default unless IO_OLLAMA_TESTS=1.
    """
    pytest.skip("Ollama model not available" if os.environ.get("IO_OLLAMA_TESTS") != "1" else "")

    # Load fixture
    fixture_path = Path(__file__).parent / "fixtures" / "utterances_route.json"
    with open(fixture_path) as f:
        utterances = json.load(f)

    # Create router with local backend
    router = Router(LocalBackend(config))

    # Test each utterance
    matches = 0
    total = len(utterances)

    for item in utterances:
        result = router.classify(item["utterance"])
        expected = item["intent"]
        if result == expected:
            matches += 1

    accuracy = matches / total
    assert accuracy >= 0.8, f"Intent match accuracy {accuracy:.2%} < 80% ({matches}/{total})"
