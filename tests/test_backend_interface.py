import datetime as dt

from io_assistant.backend.interface import Backend
from io_assistant.models_domain import ExtractionResult


def test_fakebackend_satisfies_protocol(fake_backend):
    assert isinstance(fake_backend, Backend)


def test_fakebackend_extract_returns_result(fake_backend):
    fake_backend.set_extraction(ExtractionResult(records=[]))
    out = fake_backend.extract("hi", dt.datetime.now(dt.timezone.utc))
    assert isinstance(out, ExtractionResult)


def test_fakebackend_route_returns_configured_intent(fake_backend):
    fake_backend.set_intent("store")
    assert fake_backend.route("anything") == "store"


def test_normalize_kind_and_domain():
    from io_assistant.models_domain import normalize_kind, normalize_domain

    assert normalize_kind("Gym Session") == "gym_session"
    assert normalize_kind("  ") == "note"
    assert normalize_domain("Job") == "job"
    assert normalize_domain("astrology") == "other"
    assert normalize_domain(None) is None
