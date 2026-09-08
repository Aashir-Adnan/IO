from fastapi.testclient import TestClient

from tests.conftest import requires_db
from io_assistant.service.app import create_app


@requires_db
def test_health_ok(config, fake_backend):
    app = create_app(config)
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["database"] is True
    assert body["backend_provider"] == config.backend.provider
