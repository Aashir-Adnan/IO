import re
from pathlib import Path

from fastapi.testclient import TestClient

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def test_frontend_dir_exists():
    assert (FRONTEND / "index.html").is_file()
    assert (FRONTEND / "app.js").is_file()


def test_no_external_urls_in_frontend():
    offenders = []
    pattern = re.compile(r"https?://(?!(127\.0\.0\.1|localhost))", re.I)
    for path in FRONTEND.rglob("*"):
        if path.suffix.lower() in {".html", ".js", ".css"}:
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, "external URL(s) in frontend:\n" + "\n".join(offenders)


def test_index_served(config):
    from io_assistant.service.app import create_app
    app = create_app(config, orchestrator=object(), engine=object())
    with TestClient(app) as c:
        r = c.get("/app/")
    assert r.status_code == 200 and "<html" in r.text.lower()
