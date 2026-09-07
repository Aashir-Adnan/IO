import json

from io_assistant.extract.schema import SCHEMA_JSON, FEWSHOT
from io_assistant.models_domain import ExtractionResult


def test_schema_hint_names_the_top_level_arrays():
    for key in ("people", "places", "items", "occasions", "records"):
        assert key in SCHEMA_JSON
    assert "kind" in SCHEMA_JSON and "domain" in SCHEMA_JSON
    assert "confidence" in SCHEMA_JSON


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
