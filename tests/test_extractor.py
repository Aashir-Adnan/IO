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

    # This is an opt-in quality signal for the light-profile model
    # (llama3.2:3b), not a hard gate. A 3B model gets most cases right but is
    # not perfect run-to-run, so we assert a pass RATE, not every case — the
    # same philosophy as test_router.py's intent-match threshold. If this drops
    # well below the threshold, the light profile has regressed or the prompt
    # needs work (see .claude/knowledge/model-backends.md).
    THRESHOLD = 0.75

    ex = Extractor(LocalBackend(config))
    data = json.loads(pathlib.Path("tests/fixtures/utterances_store.json").read_text())
    now = dt.datetime.now(dt.timezone.utc)
    passed = 0
    for case in data:
        exp = case["expect"]
        r = ex.run(case["utterance"], now)
        if r is None:
            print(f"CASE FAIL (no result): {case['utterance']!r}")
            continue
        names = {p.name.lower() for p in r.people}
        people_ok = all(
            any(want.lower() in n or n in want.lower() for n in names)
            for want in exp.get("people", [])
        )
        records_ok = "records" not in exp or len(r.records) == exp["records"]
        if people_ok and records_ok:
            passed += 1
        else:
            print(
                f"CASE FAIL: {case['utterance']!r} people_ok={people_ok} "
                f"records_ok={records_ok} got_people={sorted(names)} "
                f"got_records={[(x.kind, x.domain, x.title) for x in r.records]}"
            )
        # soft signal only
        if r.records:
            if "kind" in exp and exp["kind"] != r.records[0].kind:
                print(f"WARN kind: wanted {exp['kind']} got {r.records[0].kind} for {case['utterance']!r}")
            if "domain" in exp and exp["domain"] != r.records[0].domain:
                print(f"WARN domain: wanted {exp['domain']} got {r.records[0].domain} for {case['utterance']!r}")

    rate = passed / len(data)
    print(f"extraction pass rate: {passed}/{len(data)} = {rate:.0%}")
    assert rate >= THRESHOLD, f"pass rate {rate:.0%} below {THRESHOLD:.0%}"
