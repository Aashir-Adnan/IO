import json
import shutil
import subprocess
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def _node(script: str) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    r = subprocess.run([node, "--input-type=module", "-e", script],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_reveal_holds_then_types_then_cancels():
    out = _node(f"""
      import {{ revealText }} from {json.dumps((FRONTEND / 'typing.js').as_uri())};
      let now = 0;
      const rafq = [];
      global.performance = {{ now: () => now }};
      global.requestAnimationFrame = (fn) => rafq.push(fn);
      const el = {{ textContent: "" }};
      let done = false;
      const cancel = revealText(el, "hello world", {{ cps: 1000, minThinkMs: 600, clock: () => now, onDone: () => {{ done = true; }} }});
      const pump = () => {{ const q = rafq.splice(0); q.forEach((f) => f()); }};
      now = 300; pump();
      const early = el.textContent;
      now = 1600; pump(); pump(); pump();
      const mid = el.textContent.length;
      cancel();
      console.log(JSON.stringify({{ early, full: el.textContent, done }}));
    """)
    got = json.loads(out.strip().splitlines()[-1])
    assert got["early"] == ""          # nothing during the think hold
    assert got["full"] == "hello world"  # cancel completes instantly
    assert got["done"] is True
