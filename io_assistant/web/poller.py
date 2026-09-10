"""Tier B runtime: register trackers, poll the due ones, write `reading`
records, and read them back for a today-vs-prior delta.

Everything here is deterministic. The only network calls are a SearXNG query
(`instant` extractor) or a plain page GET (`regex` extractor) — both already
sanctioned by rules/local-first.md while [web].enabled.
"""
from __future__ import annotations

import datetime as _dt
import threading

from sqlalchemy import select

from io_assistant.config import Config
from io_assistant.db import models as m
from io_assistant.web.fetch import fetch_and_extract
from io_assistant.web.search import WebSearcher
from io_assistant.web.trackers import (
    TrackerSpec, extract_reading, match_catalogue, normalize_label,
)

__all__ = [
    "register_tracker", "due_trackers", "poll_tracker", "poll_due",
    "latest_readings", "delta_reading", "TrackerPoller",
]


# --- registration ----------------------------------------------------------
def register_tracker(session, spec: TrackerSpec) -> m.Tracker:
    norm = normalize_label(spec.label)
    row = session.execute(
        select(m.Tracker).where(m.Tracker.norm == norm)
    ).scalar_one_or_none()
    if row is None:
        row = m.Tracker(
            label=spec.label, norm=norm, domain=spec.domain,
            source_url=spec.source_url or f"searxng:{spec.extractor.get('query', '')}",
            extractor=spec.extractor, interval_min=spec.interval_min, enabled=True,
        )
        session.add(row)
        session.flush()
    else:
        row.enabled = True
        row.extractor = spec.extractor
        row.interval_min = spec.interval_min
    return row


# --- polling -------------------------------------------------------------
def due_trackers(session, now: _dt.datetime) -> list[m.Tracker]:
    rows = session.execute(
        select(m.Tracker).where(m.Tracker.enabled)
    ).scalars().all()
    out = []
    for t in rows:
        if t.last_polled_at is None:
            out.append(t)
        elif t.last_polled_at + _dt.timedelta(minutes=t.interval_min) <= now:
            out.append(t)
    return out


def _write_reading(session, tracker: m.Tracker, value: str, unit: str,
                   source: str, now: _dt.datetime) -> m.Record:
    u = m.Utterance(text=f"[poll] {tracker.label}", source="web",
                    captured_at=now, resolved_intent="store", marker="tracker")
    session.add(u)
    session.flush()
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = None
    rec = m.Record(
        kind="reading", domain=tracker.domain, title=tracker.label,
        body=f"{value} {unit}".strip(),
        occurred_at=now,
        attributes={"value": numeric, "raw": value, "unit": unit, "source": source},
        source_utterance_id=u.id,
    )
    session.add(rec)
    session.flush()
    return rec


def poll_tracker(session, searcher: WebSearcher, tracker: m.Tracker,
                 now: _dt.datetime) -> bool:
    """Fetch the tracker's source, extract a value, write a reading. Returns
    True on success; on failure records `last_error` and returns False."""
    ext = tracker.extractor or {}
    instant_text = page_text = ""
    source = tracker.source_url or ""
    try:
        if ext.get("type") == "instant":
            resp = searcher.search(ext.get("query") or tracker.label, categories="general")
            instant_text = resp.instant[0].text if resp.instant else ""
            if resp.instant and resp.instant[0].url:
                source = resp.instant[0].url
        elif ext.get("type") == "regex":
            page = fetch_and_extract(tracker.source_url, max_bytes=400_000)
            page_text = page.text
        else:
            tracker.last_error = f"unknown extractor {ext.get('type')!r}"
            tracker.last_polled_at = now
            return False
    except Exception as e:  # noqa: BLE001 — poller must not die (incl. WebFetchError)
        tracker.last_error = str(e)[:400]
        tracker.last_polled_at = now
        return False

    got = extract_reading(ext, instant_text=instant_text, page_text=page_text)
    tracker.last_polled_at = now
    if got is None:
        tracker.last_error = "no value found"
        return False
    value, unit = got
    _write_reading(session, tracker, value, unit, source, now)
    tracker.last_value, tracker.last_unit, tracker.last_error = value, unit or None, None
    return True


def poll_due(session, config: Config, now: _dt.datetime, *,
             searcher: WebSearcher | None = None) -> int:
    searcher = searcher or WebSearcher(config.web)
    n = 0
    for t in due_trackers(session, now):
        if poll_tracker(session, searcher, t, now):
            n += 1
    return n


# --- read-back -----------------------------------------------------------
def latest_readings(session, label: str, *, limit: int = 30) -> list[m.Record]:
    norm = normalize_label(label)
    return session.execute(
        select(m.Record)
        .where(m.Record.kind == "reading", m.Record.title.ilike(label))
        .order_by(m.Record.occurred_at.desc())
        .limit(limit)
    ).scalars().all() or session.execute(
        select(m.Record)
        .where(m.Record.kind == "reading",
               m.Record.title.ilike(f"%{norm}%"))
        .order_by(m.Record.occurred_at.desc())
        .limit(limit)
    ).scalars().all()


def delta_reading(readings: list[m.Record], now: _dt.datetime) -> dict | None:
    """Latest reading vs the most recent one from an earlier calendar day.
    Pure Python — no model, no SQL date math."""
    if not readings:
        return None
    latest = readings[0]
    lv = (latest.attributes or {}).get("value")
    unit = (latest.attributes or {}).get("unit") or ""
    today = now.date()
    prior = next(
        (r for r in readings[1:]
         if r.occurred_at and r.occurred_at.date() < latest.occurred_at.date()),
        None,
    )
    out = {
        "label": latest.title,
        "current": lv,
        "current_raw": (latest.attributes or {}).get("raw"),
        "unit": unit,
        "as_of": latest.occurred_at.isoformat() if latest.occurred_at else None,
        "is_today": bool(latest.occurred_at and latest.occurred_at.date() == today),
        "prior": None,
    }
    if prior is not None:
        pv = (prior.attributes or {}).get("value")
        out["prior"] = {
            "value": pv,
            "raw": (prior.attributes or {}).get("raw"),
            "as_of": prior.occurred_at.isoformat() if prior.occurred_at else None,
        }
        if isinstance(lv, (int, float)) and isinstance(pv, (int, float)):
            out["change"] = round(lv - pv, 6)
            out["pct"] = round((lv - pv) / pv * 100, 2) if pv else None
    return out


# --- background thread --------------------------------------------------
class TrackerPoller:
    """Daemon thread: poll due trackers every `tick_min` minutes. Modelled on
    files.queue.IndexQueue — concurrency 1, best-effort, never raises."""

    def __init__(self, session_factory, config: Config, *, tick_min: int = 30):
        self._sf = session_factory
        self._config = config
        self._tick = max(60.0, tick_min * 60.0)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None or not self._config.web.enabled:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def poll_now(self) -> int:
        return self._cycle()

    def _cycle(self) -> int:
        try:
            session = self._sf()
            try:
                n = poll_due(session, self._config, _dt.datetime.now(_dt.timezone.utc))
                session.commit()
                return n
            finally:
                session.close()
        except Exception:  # pragma: no cover — worker must not die
            return 0

    def _run(self) -> None:
        # small initial delay so startup isn't blocked by network
        if self._stop.wait(5.0):
            return
        while not self._stop.is_set():
            self._cycle()
            self._stop.wait(self._tick)
