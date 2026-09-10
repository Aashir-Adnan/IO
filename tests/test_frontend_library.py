import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node not installed")


def _run(js):
    r = subprocess.run([node, "--input-type=module", "-e", js],
                       capture_output=True, text=True, cwd=FRONTEND)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def test_library_view_and_api_exports():
    """The merged library view (folders + photo grid + inspector) and the
    file / gallery API surface it needs."""
    js = f"""
    import * as lib from {json.dumps((FRONTEND / 'views/library.js').as_uri())};
    if (typeof lib.mount !== 'function') throw new Error('no library.mount');
    if (typeof lib.mountFolders !== 'function') throw new Error('no library.mountFolders');

    import * as card from {json.dumps((FRONTEND / 'components/card.js').as_uri())};
    if (typeof card.renderCard !== 'function') throw new Error('no renderCard');

    import * as api from {json.dumps((FRONTEND / 'api.js').as_uri())};
    const c = api.Api('');
    const need = ['files','registerFile','forgetFile','reindexFiles','filesStatus',
                  'fileContent','openFolder','caption','captionConfirm','transcribeAudio'];
    for (const m of need)
      if (typeof c[m] !== 'function') throw new Error('missing api.' + m);
    console.log('ok');
    """
    assert _run(js) == "ok"


def test_history_component_exports():
    js = f"""
    import * as h from {json.dumps((FRONTEND / 'components/history.js').as_uri())};
    if (typeof h.HistoryList !== 'function') throw new Error('no HistoryList');
    console.log('ok');
    """
    assert _run(js) == "ok"


def test_tasklist_card_has_interactive_checkbox():
    src = (FRONTEND / "components" / "card.js").read_text()
    assert "task-check" in src and "editRecord" in src


def test_records_row_has_status_toggle():
    src = (FRONTEND / "views" / "records.js").read_text()
    assert "record-check" in src


def test_mic_and_stt_wiring():
    js = f"""
    import * as mic from {json.dumps((FRONTEND / 'mic.js').as_uri())};
    if (typeof mic.createMic !== 'function') throw new Error('no createMic');
    import * as sx from {json.dumps((FRONTEND / 'vendor/soniox.js').as_uri())};
    if (typeof sx.SonioxStream !== 'function') throw new Error('no SonioxStream');
    import * as api from {json.dumps((FRONTEND / 'api.js').as_uri())};
    const c = api.Api('');
    for (const m of ['sttMode','sttStreamToken','transcribeAudio'])
      if (typeof c[m] !== 'function') throw new Error('missing api.' + m);
    console.log('ok');
    """
    assert _run(js) == "ok"
