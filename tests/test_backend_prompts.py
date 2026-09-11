"""Static assertions on the prompt text files — cheap regression guard against
accidental deletion of a rule, without needing a model call."""
from pathlib import Path

_PROMPTS = Path(__file__).resolve().parents[1] / "io_assistant" / "prompts"


def test_plan_prompt_mentions_known_lists():
    txt = (_PROMPTS / "plan.txt").read_text()
    assert "Known list" in txt and "kind_filter" in txt


def test_decide_prompt_mentions_known_lists():
    txt = (_PROMPTS / "decide.txt").read_text()
    assert "Known lists" in txt and "kind" in txt
