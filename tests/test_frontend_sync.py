import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
NOW = 1_000_000.0


def _msg(status) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    script = (
        f"import {{ syncMessage }} from {json.dumps((FRONTEND / 'sync.js').as_uri())};"
        f"console.log(JSON.stringify(syncMessage({json.dumps(status)}, {NOW})));"
    )
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _s(**kw):
    base = {"enabled": True, "mode": "drive", "signed_in": True, "syncing": False,
            "signing_in": False, "last_synced_at": None, "error": None}
    return {**base, **kw}


def test_unavailable_server():
    m = _msg(None)
    assert m["text"] == "Sync is unavailable." and m["state"] == "off"


def test_disabled_explains_how_to_turn_it_on():
    m = _msg(_s(enabled=False))
    assert "[sync] enabled = true" in m["text"] and m["state"] == "off"
    assert not (m["canSignIn"] or m["canSync"] or m["canSignOut"])


def test_signed_out_offers_sign_in_only():
    m = _msg(_s(signed_in=False))
    assert m["text"] == "Not signed in." and m["canSignIn"]
    assert not (m["canSync"] or m["canSignOut"])


def test_signing_in_is_busy():
    m = _msg(_s(signed_in=False, signing_in=True))
    assert "browser" in m["text"] and m["busy"] and not m["canSignIn"]


def test_syncing_is_busy():
    m = _msg(_s(syncing=True))
    assert m["text"] == "Syncing…" and m["busy"] and m["state"] == "busy"


@pytest.mark.parametrize("ago,text", [
    (5, "Synced just now"), (90, "Synced 1 min ago"), (600, "Synced 10 min ago"),
    (7200, "Synced 2 h ago"), (200000, "Synced 2 d ago")])
def test_last_synced_is_relative(ago, text):
    m = _msg(_s(last_synced_at=NOW - ago))
    assert m["text"] == text and m["state"] == "ok"
    assert m["canSync"] and m["canSignOut"]


def test_signed_in_but_never_synced():
    assert _msg(_s())["text"] == "Signed in. Not synced yet."


def test_error_is_shown_and_still_retryable():
    m = _msg(_s(error="quota exceeded", last_synced_at=NOW - 60))
    assert m["text"] == "Sync problem: quota exceeded" and m["state"] == "error"
    assert m["canSync"]


def test_folder_mode_has_no_sign_out():
    m = _msg(_s(mode="folder", last_synced_at=NOW - 30))
    assert m["canSync"] and not m["canSignOut"] and not m["canSignIn"]
    assert "folder" in m["where"]
