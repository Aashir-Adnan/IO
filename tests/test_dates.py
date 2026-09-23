import datetime as dt

from io_assistant.resolve.dates import (
    ground,
    is_someday_phrase,
    start_of_day,
    to_rrule,
)

NOW = dt.datetime(2026, 9, 7, 15, 0, tzinfo=dt.timezone.utc)  # a Monday


def test_none_phrase_ok():
    r = ground(None, NOW)
    assert r.ok and r.value is None


def test_empty_phrase_ok():
    r = ground("   ", NOW)
    assert r.ok and r.value is None


def test_today_snaps_to_noon():
    r = ground("today", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 7)
    assert (r.value.hour, r.value.minute) == (12, 0)


def test_now_stays_exact():
    r = ground("now", NOW)
    assert r.ok and r.value == NOW


def test_yesterday():
    r = ground("yesterday", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 6)
    assert r.value.hour == 12


def test_tomorrow():
    r = ground("tomorrow", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 8)


def test_this_morning():
    r = ground("this morning", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 7)
    assert (r.value.hour, r.value.minute) == (9, 0)


def test_tonight():
    r = ground("tonight", NOW)
    assert r.ok and (r.value.hour, r.value.minute) == (20, 0)


def test_this_evening():
    r = ground("this evening", NOW)
    assert r.ok and r.value.hour == 20


def test_this_afternoon():
    r = ground("this afternoon", NOW)
    assert r.ok and r.value.hour == 14


def test_in_3_days():
    r = ground("in 3 days", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 10)


def test_3_days_ago():
    r = ground("3 days ago", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 4)


def test_2_years_ago():
    r = ground("2 years ago", NOW)
    assert r.ok and r.value.date() == dt.date(2024, 9, 7)


def test_for_2_years_now():
    r = ground("for 2 years now", NOW)
    assert r.ok and r.value.date() == dt.date(2024, 9, 7)


def test_3_weeks_ago():
    r = ground("3 weeks ago", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 8, 17)


def test_6_months_ago():
    r = ground("6 months ago", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 3, 7)


def test_in_2_weeks():
    r = ground("in 2 weeks", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 21)


def test_a_year_ago():
    r = ground("a year ago", NOW)
    assert r.ok and r.value.date() == dt.date(2025, 9, 7)


def test_last_month():
    r = ground("last month", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 8, 7)


def test_last_year():
    r = ground("last year", NOW)
    assert r.ok and r.value.date() == dt.date(2025, 9, 7)


def test_last_week():
    r = ground("last week", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 8, 31)


def test_next_week():
    r = ground("next week", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 14)


def test_last_friday():
    r = ground("last Friday", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 4)


def test_last_monday():
    # NOW is Monday -> go back 7 days
    r = ground("last Monday", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 8, 31)


def test_this_friday():
    r = ground("this Friday", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 11)


def test_next_wednesday():
    r = ground("next Wednesday", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 9)


def test_bare_weekday_future():
    r = ground("Wednesday", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 9)


def test_leading_on():
    r = ground("on tomorrow", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 8)


def test_case_insensitive():
    r = ground("YESTERDAY", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 6)


def test_unparseable_not_ok():
    r = ground("sometime around the harvest festival", NOW)
    assert not r.ok and r.value is None


def test_tz_preserved():
    r = ground("in 5 days", NOW)
    assert r.value.tzinfo == NOW.tzinfo


def test_rrule_every_monday():
    assert to_rrule("every Monday") == "FREQ=WEEKLY;BYDAY=MO"


def test_rrule_mondays():
    assert to_rrule("mondays") == "FREQ=WEEKLY;BYDAY=MO"


def test_rrule_every_mon():
    assert to_rrule("every mon") == "FREQ=WEEKLY;BYDAY=MO"


def test_rrule_every_weekday():
    assert to_rrule("every weekday") == "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"


def test_rrule_daily():
    assert to_rrule("daily") == "FREQ=DAILY"
    assert to_rrule("every day") == "FREQ=DAILY"


def test_rrule_weekly():
    assert to_rrule("weekly") == "FREQ=WEEKLY"


def test_rrule_monthly():
    assert to_rrule("monthly") == "FREQ=MONTHLY"


def test_rrule_yearly():
    assert to_rrule("annually") == "FREQ=YEARLY"


def test_rrule_unknown_none():
    assert to_rrule("once in a blue moon") is None


def test_rrule_none():
    assert to_rrule(None) is None


# --- absolute / ISO date grounding (the dateutil fallback) --------------------

def test_absolute_the_10th_of_september():
    r = ground("the 10th of september", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 10)


def test_absolute_with_relative_prefix():
    # the user's real phrasing — "tomorrow, the 10th of september"
    r = ground("tomorrow, the 10th of september", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 10)


def test_iso_date_grounds():
    r = ground("2026-12-01", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 12, 1)


def test_bare_month_day_in_the_past_rolls_to_next_year():
    r = ground("3rd of january", NOW)   # Jan already passed relative to Sep
    assert r.ok and r.value.date() == dt.date(2027, 1, 3)


def test_true_garbage_still_gates():
    r = ground("some time soon-ish maybe", NOW)
    assert r.ok is False and r.value is None


def test_absolute_date_equal_to_today_still_grounds():
    # regression: "the 10th of september" grounded on the 10th landed exactly on
    # the noon default and was wrongly rejected as "learned nothing" (→ a 422 on
    # PATCH /record). A month/day token means the phrase really is a date.
    today = dt.datetime(2026, 9, 10, 9, 30, tzinfo=dt.timezone.utc)
    r = ground("the 10th of september", today)
    assert r.ok and r.value.date() == dt.date(2026, 9, 10)


# --- someday phrasing (Task 10 / Group E fix round) ------------------------


def test_someday_phrases_ground_to_dateless_not_gated():
    for phrase in ("someday", "eventually", "no rush"):
        r = ground(phrase, NOW)
        assert r.ok is True and r.value is None, phrase


def test_next_friday_still_grounds_normally():
    # unaffected by the someday branch — a plain date phrase with no someday
    # wording in it.
    r = ground("next friday", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 11)


def test_mixed_someday_and_real_date_still_grounds_the_date():
    # "by Friday, no rush" must not let "no rush" swallow the real weekday.
    r = ground("Friday, no rush", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 11)

    r2 = ground("Tuesday whenever", NOW)
    assert r2.ok and r2.value.date() == dt.date(2026, 9, 8)


def test_one_day_idiom_is_not_swallowed_as_someday():
    # the "one day" alternative was dropped from _SOMEDAY for being over-broad
    # (matched "one day at a time" / "in one day"); this phrase is not really
    # "no particular date" as a due phrase, so it fails to ground as before.
    r = ground("one day at a time", NOW)
    assert r.ok is False and r.value is None


def test_start_of_day_is_local_midnight():
    d = dt.datetime(2026, 9, 7, 18, 30, 45, tzinfo=dt.timezone.utc)
    assert start_of_day(d) == dt.datetime(2026, 9, 7, 0, 0, tzinfo=dt.timezone.utc)


def test_is_someday_phrase():
    assert is_someday_phrase("someday") is True
    assert is_someday_phrase("eventually") is True
    assert is_someday_phrase("no rush") is True
    assert is_someday_phrase(None) is False
    assert is_someday_phrase("") is False
    assert is_someday_phrase("next friday") is False
