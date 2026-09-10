from io_assistant.actions.registry import (
    REGISTRY, describe_capabilities, validate_action,
)


def test_complete_record_capability_registered():
    assert "complete_record" in REGISTRY
    assert "what" in REGISTRY["complete_record"].args
    assert "complete_record" in describe_capabilities(
        files_enabled=False, web_enabled=False)


def test_complete_record_args_are_validated():
    assert validate_action("complete_record", {"what": "the plants", "x": 1}) == (
        "complete_record", {"what": "the plants"})
