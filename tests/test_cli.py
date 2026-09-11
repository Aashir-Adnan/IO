import datetime as dt

from sqlalchemy import text
from typer.testing import CliRunner

from tests.conftest import requires_db
from io_assistant.cli import app

runner = CliRunner()


@requires_db
def test_list_shows_collections(monkeypatch, config, engine):
    monkeypatch.setattr("io_assistant.cli.load_config", lambda *a, **k: config)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO utterances (text, source, captured_at) "
            "VALUES ('x', 'text', :now)"
        ), {"now": dt.datetime.now(dt.timezone.utc)})
        conn.execute(text(
            "INSERT INTO collections (name, kind_slug, synonyms, field_hint) "
            "VALUES ('watchlist', 'watchlist', '[\"watchlist\"]'::jsonb, "
            "'{\"checkable\": true}'::jsonb)"
        ))
    try:
        r = runner.invoke(app, ["list"])
        assert r.exit_code == 0 and "watchlist" in r.stdout
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "TRUNCATE collections, records, utterances RESTART IDENTITY CASCADE"
            ))


@requires_db
def test_list_name_shows_items_open_first(monkeypatch, config, engine):
    monkeypatch.setattr("io_assistant.cli.load_config", lambda *a, **k: config)
    with engine.begin() as conn:
        uid = conn.execute(text(
            "INSERT INTO utterances (text, source, captured_at) "
            "VALUES ('x', 'text', :now) RETURNING id"
        ), {"now": dt.datetime.now(dt.timezone.utc)}).scalar_one()
        conn.execute(text(
            "INSERT INTO collections (name, kind_slug, synonyms, field_hint) "
            "VALUES ('watchlist', 'watchlist', '[\"watchlist\"]'::jsonb, "
            "'{\"checkable\": true}'::jsonb)"
        ))
        conn.execute(text(
            "INSERT INTO records (kind, title, status, attributes, source_utterance_id) "
            "VALUES ('watchlist', 'Dune', 'done', '{}'::jsonb, :uid), "
            "('watchlist', 'Arrival', 'open', '{}'::jsonb, :uid)"
        ), {"uid": uid})
    try:
        r = runner.invoke(app, ["list", "watchlist"])
        assert r.exit_code == 0
        out = r.stdout
        assert "Arrival" in out and "Dune" in out
        assert out.index("Arrival") < out.index("Dune")
    finally:
        with engine.begin() as conn:
            conn.execute(text(
                "TRUNCATE collections, records, utterances RESTART IDENTITY CASCADE"
            ))


@requires_db
def test_list_unknown_name_errors(monkeypatch, config, engine):
    monkeypatch.setattr("io_assistant.cli.load_config", lambda *a, **k: config)
    r = runner.invoke(app, ["list", "nonexistent-thing"])
    assert r.exit_code != 0
