"""Deterministic resolution of relative time phrases.

Pure module: stdlib + python-dateutil only. Must not import from
``io_assistant.backend`` or call any model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta

__all__ = [
    "DateResult",
    "ground",
    "to_rrule",
    "start_of_day",
    "is_someday_phrase",
]


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

# "no particular date" phrasing — a groundable answer of "no date", NOT an
# ungroundable failure. A bare task with one of these stays dateless instead of
# defaulting to due-today. No bare "one day" alternative — it over-matches
# idioms like "one day at a time" / "in one day" that aren't expressing "no
# particular date".
_SOMEDAY = re.compile(
    r"\b(some\s?day|eventually|some\s?point|no rush|no hurry|whenever|"
    r"at some point|down the line|in the future)\b",
    re.IGNORECASE,
)


def is_someday_phrase(text: str | None) -> bool:
    """True when a phrase expresses 'no particular date' ('someday',
    'eventually', 'no rush') rather than a concrete groundable time."""
    return bool(text and _SOMEDAY.search(text))


def start_of_day(d: datetime) -> datetime:
    """Local midnight of ``d`` — the default due moment for a bare task."""
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


# a digit, a month name, or a weekday name — enough to say a phrase carries a
# real date, so a "someday"-flavoured phrase that also names one ("by Friday,
# no rush") is not silently swallowed as dateless.
_WEEKDAY_TOKEN = r"\b(?:" + "|".join(_WEEKDAYS.keys()) + r")\b"
_DATEISH = re.compile(
    r"\d|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|" + _WEEKDAY_TOKEN,
    re.IGNORECASE,
)

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
    if text.startswith("for "):
        text = text[4:].strip()
    return text


_UNITS = {
    "day": "days",
    "days": "days",
    "week": "weeks",
    "weeks": "weeks",
    "month": "months",
    "months": "months",
    "year": "years",
    "years": "years",
}


def _at_time(base: datetime, hour: int, minute: int = 0) -> datetime:
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


# A bare day reference ("today", "yesterday", "last Friday", "3 days ago") has
# no time-of-day; snap it to local noon so it reads back as a day, not a
# timestamp, and never crosses a day boundary on a timezone shift.
_DAY_HOUR = 12


def _noon(d: datetime) -> datetime:
    return _at_time(d, _DAY_HOUR)


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

    # A mixed phrase ("by Friday, no rush", "Tuesday whenever") carries a real
    # date token alongside the someday marker — ground the date, don't let the
    # someday wording swallow it.
    if is_someday_phrase(phrase) and not _DATEISH.search(phrase):
        return DateResult(None, True)

    text = _normalize(phrase)

    if text == "now":
        return DateResult(now, True)
    if text == "today":
        return DateResult(_noon(now), True)
    if text == "this morning":
        return DateResult(_at_time(now, 9), True)
    if text in ("tonight", "this evening"):
        return DateResult(_at_time(now, 20), True)
    if text == "this afternoon":
        return DateResult(_at_time(now, 14), True)
    if text == "yesterday":
        return DateResult(_noon(now - timedelta(days=1)), True)
    if text == "tomorrow":
        return DateResult(_noon(now + timedelta(days=1)), True)
    if text == "last week":
        return DateResult(_noon(now - timedelta(days=7)), True)
    if text == "next week":
        return DateResult(_noon(now + timedelta(days=7)), True)
    if text == "last month":
        return DateResult(_noon(now - relativedelta(months=1)), True)
    if text == "next month":
        return DateResult(_noon(now + relativedelta(months=1)), True)
    if text == "last year":
        return DateResult(_noon(now - relativedelta(years=1)), True)
    if text == "next year":
        return DateResult(_noon(now + relativedelta(years=1)), True)

    # "2 years now" / "for 2 years now" — an ongoing state that began N units ago
    m = re.fullmatch(r"(\d+|a|an) ([a-z]+?)s? now", text)
    if m and m.group(2) in _UNITS:
        qty = 1 if m.group(1) in ("a", "an") else int(m.group(1))
        return DateResult(_noon(now - relativedelta(**{_UNITS[m.group(2)]: qty})), True)

    m = re.fullmatch(r"(?:in )?(\d+|a|an) ([a-z]+?)s? ago", text)
    if not m:
        m = re.fullmatch(r"(?:in )?(\d+|a|an) ([a-z]+?)s?(?: from now)?", text)
        sign = 1
    else:
        sign = -1
    if m and m.group(2) in _UNITS:
        qty_raw = m.group(1)
        qty = 1 if qty_raw in ("a", "an") else int(qty_raw)
        unit = _UNITS[m.group(2)]
        return DateResult(_noon(now + relativedelta(**{unit: sign * qty})), True)

    m = re.fullmatch(r"(last|this|next) ([a-z]+)", text)
    if m:
        qualifier, wd = m.group(1), m.group(2)
        if wd in _WEEKDAYS:
            target = _WEEKDAYS[wd]
            if qualifier == "last":
                return DateResult(_noon(_last_weekday(now, target)), True)
            if qualifier == "this":
                return DateResult(_noon(_this_weekday(now, target)), True)
            return DateResult(_noon(_next_weekday(now, target)), True)

    if text in _WEEKDAYS:
        return DateResult(_noon(_next_weekday(now, _WEEKDAYS[text])), True)

    # Last resort — an absolute or ISO date ("the 10th of september",
    # "sept 10", "2026-09-10", "tomorrow the 10th"). dateutil is fuzzy so it
    # skips filler words and any relative prefix; the year defaults to now's.
    grounded = _parse_absolute(text, now)
    if grounded is not None:
        return DateResult(grounded, True)

    return DateResult(None, False)


def _parse_absolute(phrase: str, now: datetime) -> datetime | None:
    from dateutil import parser as _dateparser

    base = _noon(now)
    try:
        dt = _dateparser.parse(phrase, default=base, fuzzy=True)
    except (ValueError, OverflowError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now.tzinfo)
    # a fuzzy parse that landed exactly on the default AND had no date-like
    # token to work from learned nothing ("some time soon-ish maybe"). A month
    # name or digit means the phrase really is a date that just happens to fall
    # on today's noon.
    if dt == base and not _DATEISH.search(phrase):
        return None
    # a bare month/day with no year that already passed → assume next year
    if not re.search(r"\d{4}", phrase) and dt.date() < now.date() - timedelta(days=1):
        dt = dt.replace(year=dt.year + 1)
    if abs((dt - now).days) > 366 * 5:
        return None
    return dt


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
