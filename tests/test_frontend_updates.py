import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _msg(status) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = (
        f"import {{ updateMessage }} from {json.dumps((FRONTEND / 'updates.js').as_uri())};"
        f"console.log(JSON.stringify(updateMessage({json.dumps(status)})));"
    )
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_unavailable_server():
    assert _msg(None)["text"] == "Update checks are unavailable."


def test_disabled():
    m = _msg({"enabled": False})
    assert "off" in m["text"] and not m["canApply"]


def test_error_is_shown_verbatim():
    m = _msg({"enabled": True, "error": "could not resolve host"})
    assert m["text"] == "Couldn't check: could not resolve host" and not m["canApply"]


def test_up_to_date():
    m = _msg({"enabled": True, "available": False})
    assert m["text"] == "IO is up to date." and not m["canApply"]


@pytest.mark.parametrize("behind,text", [(1, "1 new change available."), (3, "3 new changes available.")])
def test_available_pluralises(behind, text):
    m = _msg({"enabled": True, "available": True, "behind": behind, "dirty": False})
    assert m["text"] == text and m["canApply"]


def test_dirty_blocks_apply_with_reason():
    m = _msg({"enabled": True, "available": True, "behind": 2, "dirty": True})
    assert not m["canApply"] and "local changes" in m["blocked"]
