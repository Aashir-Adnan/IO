import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _label(secs: float) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = (
        f"import {{ thoughtLabel }} from {json.dumps((FRONTEND / 'progress.js').as_uri())};"
        f"console.log(thoughtLabel({secs}));"
    )
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.parametrize("secs,expected", [
    (0.04, "Thought for a moment"),
    (0.9, "Thought for 0.9s"),
    (4.24, "Thought for 4.2s"),
    (12.6, "Thought for 13s"),
    (65, "Thought for 1m 5s"),
    (600, "Thought for 10m"),
])
def test_thought_label(secs, expected):
    assert _label(secs) == expected
