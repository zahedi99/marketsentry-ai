from datetime import UTC, date, datetime, time

import pytest

from market_core.sessions import LSE, NYSE, TSE, session_utc, sleep_window_utc

# Calendar used below (2026):
#   Thu 1 Oct, Fri 2 Oct, Sat 3 Oct
#   Sun 25 Oct: UK clocks go back (BST UTC+1 -> GMT UTC+0)
#   Sun 1 Nov:  US clocks go back (EDT UTC-4 -> EST UTC-5)


def utc(y: int, m: int, d: int, hh: int, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=UTC)


# --- sleep_window_utc ---------------------------------------------------------


def test_sleep_window_summer_london() -> None:
    # 23:00-07:00 London in October (BST, UTC+1) -> 22:00-06:00 UTC
    start, end = sleep_window_utc(date(2026, 10, 2), time(23, 0), time(7, 0), "Europe/London")

    assert start == utc(2026, 10, 2, 22)
    assert end == utc(2026, 10, 3, 6)


def test_sleep_window_winter_london() -> None:
    # Same local times in December (GMT, UTC+0) -> same in UTC
    start, end = sleep_window_utc(date(2026, 12, 1), time(23, 0), time(7, 0), "Europe/London")

    assert start == utc(2026, 12, 1, 23)
    assert end == utc(2026, 12, 2, 7)


def test_sleep_window_across_dst_change_is_nine_hours() -> None:
    # Clocks go back during the night, so the user sleeps an extra hour.
    start, end = sleep_window_utc(date(2026, 10, 24), time(23, 0), time(7, 0), "Europe/London")

    assert start == utc(2026, 10, 24, 22)  # 23:00 BST
    assert end == utc(2026, 10, 25, 7)  # 07:00 GMT
    assert (end - start).total_seconds() == 9 * 3600


def test_sleep_window_not_crossing_midnight() -> None:
    # Someone who sleeps 01:00-09:00: both times are on the same date.
    start, end = sleep_window_utc(date(2026, 10, 3), time(1, 0), time(9, 0), "Europe/London")

    assert start == utc(2026, 10, 3, 0)
    assert end == utc(2026, 10, 3, 8)


def test_sleep_window_other_timezone() -> None:
    # 23:00-07:00 in New York in October (EDT, UTC-4) -> 03:00-11:00 UTC
    start, end = sleep_window_utc(date(2026, 10, 2), time(23, 0), time(7, 0), "America/New_York")

    assert start == utc(2026, 10, 3, 3)
    assert end == utc(2026, 10, 3, 11)


def test_sleep_window_returns_utc() -> None:
    start, end = sleep_window_utc(date(2026, 10, 2), time(23, 0), time(7, 0), "Europe/London")

    assert start.tzinfo is UTC
    assert end.tzinfo is UTC


def test_sleep_window_rejects_equal_times() -> None:
    with pytest.raises(ValueError):
        sleep_window_utc(date(2026, 10, 2), time(7, 0), time(7, 0), "Europe/London")


# --- session_utc --------------------------------------------------------------


def test_nyse_session_summer() -> None:
    # 09:30-16:00 New York (EDT, UTC-4) -> 13:30-20:00 UTC
    assert session_utc(NYSE, date(2026, 10, 1)) == (utc(2026, 10, 1, 13, 30), utc(2026, 10, 1, 20))


def test_nyse_session_after_us_clocks_change() -> None:
    # Same local hours, but EST (UTC-5) -> one hour later in UTC
    assert session_utc(NYSE, date(2026, 11, 2)) == (utc(2026, 11, 2, 14, 30), utc(2026, 11, 2, 21))


def test_lse_session() -> None:
    # 08:00-16:30 London (BST, UTC+1) -> 07:00-15:30 UTC
    assert session_utc(LSE, date(2026, 10, 1)) == (utc(2026, 10, 1, 7), utc(2026, 10, 1, 15, 30))


def test_tse_session() -> None:
    # 09:00-15:30 Tokyo (JST, UTC+9, no DST) -> 00:00-06:30 UTC, same date
    assert session_utc(TSE, date(2026, 10, 2)) == (utc(2026, 10, 2, 0), utc(2026, 10, 2, 6, 30))


@pytest.mark.parametrize("day", [date(2026, 10, 3), date(2026, 10, 4)])  # Sat, Sun
def test_no_session_at_weekends(day: date) -> None:
    assert session_utc(NYSE, day) is None
    assert session_utc(LSE, day) is None
    assert session_utc(TSE, day) is None


def test_session_times_are_utc() -> None:
    session = session_utc(LSE, date(2026, 10, 1))

    assert session is not None
    assert session[0].tzinfo is UTC
    assert session[1].tzinfo is UTC
