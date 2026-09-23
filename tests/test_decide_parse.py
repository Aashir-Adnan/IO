import pytest

from io_assistant.backend.interface import BackendParseError
from io_assistant.decide.parse import parse_plan


def test_parses_store_with_extraction():
    raw = """{"steps":[{"kind":"store","extraction":{
        "people":[],"places":[],"items":[],"occasions":[],
        "records":[{"kind":"event","title":"lunch with Ali","confidence":0.9}]}}]}"""
    plan = parse_plan(raw, files_enabled=True)
    assert plan.steps[0].kind == "store"
    assert plan.steps[0].extraction.records[0].title == "lunch with Ali"


def test_multi_step_store_and_query():
    raw = '{"steps":[{"kind":"store","extraction":{"people":[],"places":[],"items":[],"occasions":[],"records":[{"kind":"task","title":"call mum","confidence":0.9}]}},{"kind":"query","question":"what is on friday"}]}'
    plan = parse_plan(raw, files_enabled=False)
    assert [s.kind for s in plan.steps] == ["store", "query"]
    assert plan.steps[1].question == "what is on friday"


def test_json_fences_tolerated():
    plan = parse_plan('```json\n{"steps":[{"kind":"unknown"}]}\n```', files_enabled=False)
    assert plan.steps[0].kind == "unknown"


def test_unknown_action_slug_becomes_query():
    raw = '{"steps":[{"kind":"action","action":"launch_nukes","args":{},"question":"do the thing"}]}'
    plan = parse_plan(raw, files_enabled=True)
    assert plan.steps[0].kind == "query"


def test_known_action_kept_and_args_filtered():
    raw = '{"steps":[{"kind":"action","action":"open_folder","args":{"name":"Downloads","evil":"x"}}]}'
    plan = parse_plan(raw, files_enabled=True)
    assert plan.steps[0].action == "open_folder"
    assert plan.steps[0].args == {"name": "Downloads"}


def test_bad_extraction_keeps_store_step_but_drops_extraction():
    plan = parse_plan('{"steps":[{"kind":"store","extraction":"not an object"}]}', files_enabled=False)
    assert plan.steps[0].kind == "store" and plan.steps[0].extraction is None


def test_not_json_raises():
    with pytest.raises(BackendParseError):
        parse_plan("sorry I can't do that", files_enabled=False)


def test_no_steps_raises():
    with pytest.raises(BackendParseError):
        parse_plan('{"steps":[]}', files_enabled=False)
