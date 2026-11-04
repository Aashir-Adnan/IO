"""Copy the desktop prompts into the phone's assets (run from the repo root:
`uv run python phone/tool/sync_prompts.py`). tests/test_phone_prompts_in_sync.py
fails if they drift."""
from pathlib import Path

from io_assistant.extract.schema import SCHEMA_JSON

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "phone" / "assets" / "prompts"
NAMES = ["decide.txt", "plan.txt", "respond.txt", "acknowledge.txt"]

OUT.mkdir(parents=True, exist_ok=True)
for n in NAMES:
    (OUT / n).write_bytes((ROOT / "io_assistant" / "prompts" / n).read_bytes())
(OUT / "schema.txt").write_text(SCHEMA_JSON, encoding="utf-8")
print("synced", NAMES + ["schema.txt"])
