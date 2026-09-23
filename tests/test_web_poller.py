"""Tier B runtime — register, poll, write `reading` records, read back a delta.
Real DB."""
from __future__ import annotations

import datetime as dt

import pytest

from tests.conftest import requires_db
from io_assistant.db import models as m
from io_assistant.web.poller import (
    delta_reading, due_trackers, latest_readings, poll_tracker, register_tracker,
)
from io_assistant.web.search import InstantAnswer, SearchResponse
from io_assistant.web.trackers import CATALOGUE

pytestmark = [requires_db]

NOW = dt.datetime(2026, 9, 9, 12, 0, tzinfo=dt.timezone.utc)
SPEC = CATALOGUE["usd-pkr"]


class FakeSearcher:
    def __init__(self, text):
        self._text = text

    def search(self, q, *, categories="general"):
        return SearchResponse(query=q, instant=[InstantAnswer(text=self._text,
                                                              url="https://fx.test")])


def test_register_is_idempotent(db):
    a = register_tracker(db, SPEC)
    db.flush()
    b = register_tracker(db, SPEC)
    assert a.id == b.id
    assert db.execute(m.Tracker.__table__.select()).rowcount != 0


def test_poll_writes_reading_and_updates_tracker(db):
    t = register_tracker(db, SPEC)
    db.flush()
    ok = poll_tracker(db, FakeSearcher("1 USD = 278.51 PKR"), t, NOW)
    db.flush()
    assert ok
    assert t.last_value == "278.51"
    assert t.last_polled_at == NOW
    assert t.last_error is None

    readings = latest_readings(db, "USD to PKR")
    assert len(readings) == 1
    r = readings[0]
    assert r.kind == "reading" and r.title == "USD to PKR"
    assert r.attributes["value"] == 278.51
    assert r.attributes["source"] == "https://fx.test"


def test_poll_records_error_on_no_value(db):
    t = register_tracker(db, SPEC)
    db.flush()
    ok = poll_tracker(db, FakeSearcher("no number in here"), t, NOW)
    assert not ok
    assert t.last_error == "no value found"
    assert latest_readings(db, "USD to PKR") == []


def test_due_trackers_respects_interval(db):
    t = register_tracker(db, SPEC)
    db.flush()
    assert t in due_trackers(db, NOW)                       # never polled
    t.last_polled_at = NOW
    db.flush()
    assert t not in due_trackers(db, NOW + dt.timedelta(minutes=10))
    assert t in due_trackers(db, NOW + dt.timedelta(minutes=SPEC.interval_min + 1))


def test_delta_reading_today_vs_yesterday(db):
    t = register_tracker(db, SPEC)
    db.flush()
    poll_tracker(db, FakeSearcher("1 USD = 275.00 PKR"), t,
                 NOW - dt.timedelta(days=1))
    poll_tracker(db, FakeSearcher("1 USD = 278.50 PKR"), t, NOW)
    db.flush()

    d = delta_reading(latest_readings(db, "USD to PKR"), NOW)
    assert d["current"] == 278.5
    assert d["is_today"] is True
    assert d["prior"]["value"] == 275.0
    assert d["change"] == 3.5
    assert d["pct"] == pytest.approx(1.27, abs=0.01)


def test_delta_reading_no_prior_day(db):
    t = register_tracker(db, SPEC)
    db.flush()
    poll_tracker(db, FakeSearcher("278.50"), t, NOW)
    db.flush()
    d = delta_reading(latest_readings(db, "USD to PKR"), NOW)
    assert d["prior"] is None
