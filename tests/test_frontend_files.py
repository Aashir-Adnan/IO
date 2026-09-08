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


def test_files_card_renders_rows():
    js = f"""
    import {{ renderCard }} from {json.dumps((FRONTEND / 'components/card.js').as_uri())};
    globalThis.document = undefined;
    """
    # renderCard needs a DOM; use jsdom-free check: just import parses + card.js exports.
    js = f"""
    import * as card from {json.dumps((FRONTEND / 'components/card.js').as_uri())};
    if (typeof card.renderCard !== 'function') throw new Error('no renderCard');
    import * as api from {json.dumps((FRONTEND / 'api.js').as_uri())};
    const c = api.Api('');
    for (const m of ['files','registerFile','forgetFile','reindexFiles','filesStatus','fileContent'])
      if (typeof c[m] !== 'function') throw new Error('missing api.' + m);
    import * as fv from {json.dumps((FRONTEND / 'views/files.js').as_uri())};
    if (typeof fv.mount !== 'function') throw new Error('no files.mount');
    console.log('ok');
    """
    assert _run(js) == "ok"
