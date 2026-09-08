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


def test_markdown_renders_structures():
    md = "## Title\n\n- one\n- two\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```mermaid\ngraph\n```\n\n[x](https://evil.com)"
    out = _node(f"""
      import {{ renderMarkdown }} from {json.dumps((FRONTEND / 'vendor' / 'markdown.js').as_uri())};
      const h = renderMarkdown({json.dumps(md)});
      console.log(JSON.stringify({{
        h2: h.includes('<h2>'), li: h.includes('<li>one</li>'),
        table: h.includes('<table>'), mermaid: h.includes('mermaid-src'),
        evil: h.includes('evil.com'),
      }}));
    """)
    got = json.loads(out.strip().splitlines()[-1])
    assert got["h2"] and got["li"] and got["table"] and got["mermaid"]
    assert not got["evil"]
