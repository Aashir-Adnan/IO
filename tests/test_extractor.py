import datetime as dt
import json
import os
import pathlib
import pytest
from io_assistant.extract.extractor import Extractor
from io_assistant.models_domain import ExtractionResult


class FlakyBackend:
    def __init__(self, results):  # results: list of ExtractionResult or Exception
        self._results = list(results)
        self.calls = 0

    def route(self, u):
        return "store"

    def extract(self, u, now):
        r = self._results[self.calls]
        self.calls += 1
        if isinstance(r, Exception):
            raise r
        return r

    def plan(self, *a):
        ...

    def phrase(self, *a):
        ...


def test_returns_result_first_try():
    b = FlakyBackend([ExtractionResult(records=[])])
    out = Extractor(b).run("hi", dt.datetime.now(dt.timezone.utc))
    assert isinstance(out, ExtractionResult) and b.calls == 1


def test_retries_once_then_succeeds():
    from io_assistant.backend.local import BackendParseError

    b = FlakyBackend([BackendParseError("bad"), ExtractionResult(records=[])])
    out = Extractor(b).run("hi", dt.datetime.now(dt.timezone.utc))
    assert isinstance(out, ExtractionResult) and b.calls == 2


def test_returns_none_after_two_failures():
    from io_assistant.backend.local import BackendParseError

    b = FlakyBackend([BackendParseError("x"), BackendParseError("y")])
    out = Extractor(b).run("hi", dt.datetime.now(dt.timezone.utc))
    assert out is None and b.calls == 2


@pytest.mark.ollama
@pytest.mark.skipif(os.environ.get("IO_OLLAMA_TESTS") != "1", reason="opt-in")
def test_extractor_against_fixtures(config):
    from io_assistant.backend.local import LocalBackend

    ex = Extractor(LocalBackend(config))
    data = json.loads(pathlib.Path("tests/fixtures/utterances_store.json").read_text())
    now = dt.datetime.now(dt.timezone.utc)
    for case in data:
        exp = case["expect"]
        r = ex.run(case["utterance"], now)
        assert r is not None, case["utterance"]
        # hard checks
        names = {p.name.lower() for p in r.people}
        for want in exp.get("people", []):
            assert any(
                want.lower() in n or n in want.lower() for n in names
            ), (case, names)
        if "records" in exp:
            assert len(r.records) == exp["records"], (case, r.records)
        # soft checks (warn, don't fail — model may pick a neighbouring value)
        if r.records:
            got_kind = r.records[0].kind
            got_domain = r.records[0].domain
            if "kind" in exp and exp["kind"] != got_kind:
                print(
                    f"WARN kind: wanted {exp['kind']} got {got_kind} for {case['utterance']!r}"
                )
            if "domain" in exp and exp["domain"] != got_domain:
                print(
                    f"WARN domain: wanted {exp['domain']} got {got_domain} for {case['utterance']!r}"
                )
