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
@pytest.mark.skipif(os.environ.get("IO_OLLAMA_TESTS") != "1", reason="opt-in")
def test_router_with_local_backend(config):
    """Opt-in quality signal for light-profile intent routing (llama3.2:3b).

    A coarse regression signal, not a hard gate — a 3B model classifies
    store/query/unknown at roughly 75-85% on this fixture run-to-run, so the
    threshold is a floor, not a target. If it drops well below, the router
    prompt has regressed or the light profile isn't good enough for routing
    (see .claude/knowledge/model-backends.md and backlog.md — improving the
    router prompt / routing on `quality` is a tracked follow-up).
    Skipped by default unless IO_OLLAMA_TESTS=1.
    """

    fixture_path = Path(__file__).parent / "fixtures" / "utterances_route.json"
    with open(fixture_path) as f:
        utterances = json.load(f)

    router = Router(LocalBackend(config))

    matches = 0
    total = len(utterances)
    for item in utterances:
        result = router.classify(item["utterance"])
        if result == item["intent"]:
            matches += 1
        else:
            print(f"MISS: {item['utterance']!r} wanted {item['intent']} got {result}")

    accuracy = matches / total
    print(f"router intent accuracy: {matches}/{total} = {accuracy:.0%}")
    assert accuracy >= 0.7, f"Intent match accuracy {accuracy:.2%} < 70% ({matches}/{total})"
