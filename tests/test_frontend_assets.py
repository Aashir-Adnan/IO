import re
import shutil
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
_EXT_URL = re.compile(r"https?://(?!(127\.0\.0\.1|localhost))", re.I)
_IMPORT_URL = re.compile(r"@import\s+url\(\s*['\"]?https?:", re.I)

_CORE = [
    "index.html", "app.js", "tokens.css", "app.css",
    "vendor/icons.js", "vendor/markdown.js", "state.js", "api.js", "typing.js",
]


def test_core_files_exist():
    for p in _CORE:
        assert (FRONTEND / p).is_file(), p
    assert len(list((FRONTEND / "vendor" / "fonts").glob("*.woff2"))) >= 5


def test_no_external_urls():
    bad = []
    for path in FRONTEND.rglob("*"):
        if path.suffix.lower() in {".html", ".js", ".css"}:
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if _EXT_URL.search(line) or _IMPORT_URL.search(line):
                    bad.append(f"{path.relative_to(FRONTEND)}:{i}: {line.strip()}")
    assert not bad, "external ref(s):\n" + "\n".join(bad)


def test_font_total_under_budget():
    total = sum(p.stat().st_size for p in (FRONTEND / "vendor" / "fonts").glob("*.woff2"))
    assert total < 130_000, f"fonts total {total} bytes — subset harder"


def test_js_parses_if_node_present():
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not installed")
    for f in _CORE:
        if not f.endswith(".js"):
            continue
        r = subprocess.run([node, "--check", str(FRONTEND / f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"{f}: {r.stderr}"


def test_index_served(config):
    from io_assistant.service.app import create_app
    app = create_app(config, orchestrator=object(), engine=object(),
                     conversations=object(), voice=object())
    with TestClient(app) as c:
        r = c.get("/app/")
    assert r.status_code == 200 and "<html" in r.text.lower()
