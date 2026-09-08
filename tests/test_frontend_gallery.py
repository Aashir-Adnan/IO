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


def test_gallery_and_api_exports():
    js = f"""
    import * as g from {json.dumps((FRONTEND / 'views/gallery.js').as_uri())};
    if (typeof g.mount !== 'function') throw new Error('no gallery.mount');
    import * as api from {json.dumps((FRONTEND / 'api.js').as_uri())};
    const c = api.Api('');
    for (const m of ['openFolder','caption','captionConfirm','transcribeAudio'])
      if (typeof c[m] !== 'function') throw new Error('missing api.' + m);
    console.log('ok');
    """
    assert _run(js) == "ok"
