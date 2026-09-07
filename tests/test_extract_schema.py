import json

from io_assistant.extract.schema import SCHEMA_JSON, FEWSHOT
from io_assistant.models_domain import ExtractionResult


def test_schema_is_valid_json_and_mentions_records():
    obj = json.loads(SCHEMA_JSON)
    assert "properties" in obj
    assert "records" in json.dumps(obj)


def test_fewshot_examples_parse_as_extraction_results():
    # every ```json block in FEWSHOT must validate
    blocks = [b.split("```")[0] for b in FEWSHOT.split("```json")[1:]]
    assert blocks, "no examples found"
    for b in blocks:
        ExtractionResult.model_validate_json(b)


def test_fixtures_file_wellformed():
    import pathlib

    data = json.loads(pathlib.Path("tests/fixtures/utterances_store.json").read_text())
    assert len(data) >= 5
    assert all("utterance" in d and "expect" in d for d in data)
