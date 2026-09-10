import datetime as dt

from io_assistant.decide.planner import DecidePlanner
from io_assistant.models_domain import ExtractedRecord, ExtractionResult

NOW = dt.datetime(2026, 9, 9, tzinfo=dt.timezone.utc)


class FakeBackend:
    def __init__(self, intent="store", extraction=None):
        self._intent = intent
        self._extraction = extraction or ExtractionResult(
            records=[ExtractedRecord(kind="note", title="x", confidence=0.9)])

    def route(self, utterance, *, context=None):
        return self._intent

    def extract(self, utterance, now):
        return self._extraction


def test_split_store_carries_extraction():
    p = DecidePlanner(FakeBackend(intent="store"))
    plan = p.plan("I met Ali", NOW)
    assert len(plan.steps) == 1
    s = plan.steps[0]
    assert s.kind == "store" and s.extraction is not None
    assert s.extraction.records[0].title == "x"


def test_split_query():
    plan = DecidePlanner(FakeBackend(intent="query")).plan("what's on friday", NOW)
    assert [s.kind for s in plan.steps] == ["query"]
    assert plan.steps[0].question == "what's on friday"


def test_split_file():
    plan = DecidePlanner(FakeBackend(intent="file")).plan("open my Taxes folder", NOW)
    assert [s.kind for s in plan.steps] == ["file"]


def test_split_unknown():
    plan = DecidePlanner(FakeBackend(intent="unknown")).plan("hello there", NOW)
    assert [s.kind for s in plan.steps] == ["unknown"]


def test_split_empty_utterance_is_unknown():
    plan = DecidePlanner(FakeBackend(intent="store")).plan("   ", NOW)
    assert plan.steps[0].kind == "unknown"


def test_extraction_failure_yields_store_step_with_none():
    class Bad(FakeBackend):
        def extract(self, utterance, now):
            from io_assistant.backend.interface import BackendParseError
            raise BackendParseError("nope")

    plan = DecidePlanner(Bad(intent="store")).plan("garble", NOW)
    assert plan.steps[0].kind == "store" and plan.steps[0].extraction is None
