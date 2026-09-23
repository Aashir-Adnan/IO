from fastapi.testclient import TestClient

from io_assistant.service.app import create_app


def _app(config):
    return create_app(config, orchestrator=object(), engine=object(),
                      conversations=object(), voice=object())


def test_no_token_configured_is_open_exactly_as_today(config):
    assert config.service.remote_token == ""
    with TestClient(_app(config)) as c:
        assert c.get("/").status_code == 200
        assert c.get("/health").status_code == 200


def test_token_configured_requires_the_header(config):
    config.service.remote_token = "s3cret"
    with TestClient(_app(config)) as c:
        assert c.get("/").status_code == 401


def test_wrong_token_is_rejected(config):
    config.service.remote_token = "s3cret"
    with TestClient(_app(config)) as c:
        r = c.get("/", headers={"Authorization": "Bearer wrong"})
        assert r.status_code == 401


def test_correct_bearer_token_is_allowed(config):
    config.service.remote_token = "s3cret"
    with TestClient(_app(config)) as c:
        r = c.get("/", headers={"Authorization": "Bearer s3cret"})
        assert r.status_code == 200


def test_health_is_always_open_even_with_a_token_set(config):
    config.service.remote_token = "s3cret"
    with TestClient(_app(config)) as c:
        assert c.get("/health").status_code == 200
