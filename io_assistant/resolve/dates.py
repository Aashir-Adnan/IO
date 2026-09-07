"""Deterministic resolution of relative time phrases.

Pure module: stdlib + python-dateutil only. Must not import from
``io_assistant.backend`` or call any model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

__all__ = ["DateResult", "ground", "to_rrule"]


@dataclass(frozen=True)
class DateResult:
    value: datetime | None
    ok: bool


_WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_RRULE_WEEKDAY_CODE = {
    0: "MO",
    1: "TU",
    2: "WE",
    3: "TH",
    4: "FR",
    5: "SA",
    6: "SU",
}


def _normalize(phrase: str) -> str:
    text = phrase.strip().lower()
    text = re.sub(r"\s+", " ", text)
    if text.startswith("on "):
        text = text[3:].strip()
    return text


def _at_time(base: datetime, hour: int, minute: int = 0) -> datetime:
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _last_weekday(now: datetime, target: int) -> datetime:
    delta = (now.weekday() - target) % 7
    if delta == 0:
        delta = 7
    return now - timedelta(days=delta)


def _this_weekday(now: datetime, target: int) -> datetime:
    week_start = now - timedelta(days=now.weekday())
    return week_start + timedelta(days=target)


def _next_weekday(now: datetime, target: int) -> datetime:
    delta = (target - now.weekday()) % 7
    if delta == 0:
        delta = 7
    return now + timedelta(days=delta)


def ground(phrase: str | None, now: datetime) -> DateResult:
    if phrase is None or not phrase.strip():
        return DateResult(None, True)

    text = _normalize(phrase)

    if text in ("today", "now"):
        return DateResult(now, True)
    if text == "this morning":
        return DateResult(_at_time(now, 9), True)
    if text in ("tonight", "this evening"):
        return DateResult(_at_time(now, 20), True)
    if text == "this afternoon":
        return DateResult(_at_time(now, 14), True)
    if text == "yesterday":
        return DateResult(now - timedelta(days=1), True)
    if text == "tomorrow":
        return DateResult(now + timedelta(days=1), True)
    if text == "last week":
        return DateResult(now - timedelta(days=7), True)
    if text == "next week":
        return DateResult(now + timedelta(days=7), True)

    m = re.fullmatch(r"(?:in )?(\d+) days?(?: from now)?", text)
    if m:
        return DateResult(now + relativedelta(days=int(m.group(1))), True)
    m = re.fullmatch(r"(\d+) days? ago", text)
    if m:
        return DateResult(now - relativedelta(days=int(m.group(1))), True)

    m = re.fullmatch(r"(last|this|next) ([a-z]+)", text)
    if m:
        qualifier, wd = m.group(1), m.group(2)
        if wd in _WEEKDAYS:
            target = _WEEKDAYS[wd]
            if qualifier == "last":
                return DateResult(_last_weekday(now, target), True)
            if qualifier == "this":
                return DateResult(_this_weekday(now, target), True)
            return DateResult(_next_weekday(now, target), True)

    if text in _WEEKDAYS:
        return DateResult(_next_weekday(now, _WEEKDAYS[text]), True)

    return DateResult(None, False)


def to_rrule(phrase: str | None) -> str | None:
    if phrase is None or not phrase.strip():
        return None

    text = _normalize(phrase)

    if text in ("every day", "daily", "each day"):
        return "FREQ=DAILY"
    if text in ("every weekday", "weekdays", "every week day"):
        return "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    if text in ("every week", "weekly"):
        return "FREQ=WEEKLY"
    if text in ("every month", "monthly"):
        return "FREQ=MONTHLY"
    if text in ("every year", "yearly", "annually"):
        return "FREQ=YEARLY"

    m = re.fullmatch(r"every ([a-z]+)", text)
    if m and m.group(1) in _WEEKDAYS:
        return f"FREQ=WEEKLY;BYDAY={_RRULE_WEEKDAY_CODE[_WEEKDAYS[m.group(1)]]}"

    m = re.fullmatch(r"([a-z]+)s", text)
    if m and m.group(1) in _WEEKDAYS:
        return f"FREQ=WEEKLY;BYDAY={_RRULE_WEEKDAY_CODE[_WEEKDAYS[m.group(1)]]}"

    return None
