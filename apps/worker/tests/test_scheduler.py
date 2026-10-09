from datetime import UTC, datetime
from datetime import time as clock_time

import pytest

from worker.scheduler import (
    MIN_INTERVAL_SECONDS,
    in_sleep_window,
    interval_for_budget,
    window_hours,
)

LONDON = "Europe/London"
SLEEP, WAKE = clock_time(23, 0), clock_time(7, 0)


# --- pacing ---------------------------------------------------------------------


def test_eight_symbols_over_an_eight_hour_night() -> None:
    # 800 / 8 = 100 captures allowed; 8h = 28800s -> one every 288s (~5 min)
    assert interval_for_budget(8, hours=8) == 288


def test_eight_symbols_all_day() -> None:
    # 100 captures spread over 24h -> one every 864s (~14 min)
    assert interval_for_budget(8, hours=24) == 864


def test_interval_never_below_one_minute() -> None:
    assert interval_for_budget(1, hours=1) == MIN_INTERVAL_SECONDS


@pytest.mark.parametrize(("symbols", "hours"), [(0, 8), (8, 0), (801, 8)])
def test_impossible_pacing_is_rejected(symbols: int, hours: float) -> None:
    with pytest.raises(ValueError):
        interval_for_budget(symbols, hours=hours)


def test_window_hours() -> None:
    assert window_hours(SLEEP, WAKE) == 8
    assert window_hours(clock_time(1, 0), clock_time(9, 30)) == 8.5


# --- sleep window ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 10, 9, 21, 59, tzinfo=UTC), False),  # 22:59 BST, before bed
        (datetime(2026, 10, 9, 22, 0, tzinfo=UTC), True),  # 23:00 BST, asleep
        (datetime(2026, 10, 10, 2, 0, tzinfo=UTC), True),  # 03:00 BST, after midnight
        (datetime(2026, 10, 10, 5, 59, tzinfo=UTC), True),  # 06:59 BST
        (datetime(2026, 10, 10, 6, 0, tzinfo=UTC), False),  # 07:00 BST, awake
        (datetime(2026, 10, 10, 12, 0, tzinfo=UTC), False),  # midday
    ],
)
def test_in_sleep_window(now: datetime, expected: bool) -> None:
    assert in_sleep_window(now, SLEEP, WAKE, LONDON) is expected


def test_in_sleep_window_in_winter_time() -> None:
    # December, London = UTC: 23:30 UTC is 23:30 local, asleep
    assert in_sleep_window(datetime(2026, 12, 1, 23, 30, tzinfo=UTC), SLEEP, WAKE, LONDON)
    assert not in_sleep_window(datetime(2026, 12, 1, 22, 30, tzinfo=UTC), SLEEP, WAKE, LONDON)
