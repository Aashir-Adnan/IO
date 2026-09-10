"""Opt-in quality signal for the combined `decide` prompt on the Anthropic
backend. A coarse regression floor, not a target — like test_router.py.

    IO_ANTHROPIC_TESTS=1 uv run pytest tests/test_decide_eval.py -q -s

Each case lists the acceptable step kinds; a run "matches" if the set of step
kinds the planner produced is a subset of the acceptable set and non-empty.
"""
import json
import os
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.anthropic,
    pytest.mark.skipif(os.environ.get("IO_ANTHROPIC_TESTS") != "1", reason="opt-in"),
]

THRESHOLD = 0.75


def test_decide_prompt_quality(config):
    import datetime as dt

    from io_assistant._env import load_env_once
    load_env_once()   # pick up ANTHROPIC_AUTH_TOKEN from repo-root .env

    from io_assistant.backend.anthropic_backend import AnthropicBackend
    from io_assistant.decide.planner import DecidePlanner

    config.backend.provider = "anthropic"
    config.backend.decide = "combined"
    planner = DecidePlanner(AnthropicBackend(config), config)

    cases = json.loads((Path(__file__).parent / "fixtures" / "decide_cases.json").read_text())
    now = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.timezone.utc)

    ok = 0
    for c in cases:
        plan = planner.plan(c["utterance"], now)
        got = {s.kind for s in plan.steps}
        acceptable = set(c["kinds"])
        if got and got <= acceptable:
            ok += 1
        else:
            print(f"MISS: {c['utterance']!r}  wanted {sorted(acceptable)}  got {sorted(got)}")

    rate = ok / len(cases)
    print(f"decide plan accuracy: {ok}/{len(cases)} = {rate:.0%}")
    assert rate >= THRESHOLD, f"pass rate {rate:.0%} below {THRESHOLD:.0%}"
