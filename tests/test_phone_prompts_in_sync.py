from pathlib import Path

from io_assistant.extract.schema import SCHEMA_JSON

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "phone" / "assets" / "prompts"


def test_phone_prompts_match_desktop():
    for n in ["decide.txt", "plan.txt", "respond.txt", "acknowledge.txt"]:
        assert (ASSETS / n).read_bytes() == (ROOT / "io_assistant" / "prompts" / n).read_bytes(), (
            f"{n} drifted: run `uv run python phone/tool/sync_prompts.py`")
    assert (ASSETS / "schema.txt").read_text(encoding="utf-8") == SCHEMA_JSON
