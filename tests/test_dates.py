import datetime as dt

from io_assistant.resolve.dates import ground, to_rrule

NOW = dt.datetime(2026, 9, 7, 15, 0, tzinfo=dt.timezone.utc)  # a Monday


def test_none_phrase_ok():
    r = ground(None, NOW)
    assert r.ok and r.value is None


def test_empty_phrase_ok():
    r = ground("   ", NOW)
    assert r.ok and r.value is None


def test_today():
    r = ground("today", NOW)
    assert r.ok and r.value == NOW


def test_yesterday():
    r = ground("yesterday", NOW)
    assert r.ok and r.value.date() == dt.date(2026, 9, 6)
    assert r.value.hour == 15


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
