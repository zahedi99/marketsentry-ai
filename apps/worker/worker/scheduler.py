"""Scheduler: run the capture job on a loop.

Two modes:
- `make schedule`: capture only during the user's sleep window (the product's real mode);
- `make stream`: capture continuously, for demos and development.

Pacing: the Twelve Data free tier allows 800 requests/day, and every capture costs one
request per instrument. The interval is chosen so a whole run fits inside that budget.
One RateLimiter is shared across all captures, so back-to-back runs also respect the
8 requests/minute limit.
"""

import argparse
import logging
import math
import time
from datetime import UTC, datetime, timedelta
from datetime import time as clock_time
from zoneinfo import ZoneInfo

from market_core.sessions import sleep_window_utc

log = logging.getLogger(__name__)

DAILY_REQUEST_BUDGET = 800
MIN_INTERVAL_SECONDS = 60


def interval_for_budget(
    n_symbols: int, hours: float, daily_budget: int = DAILY_REQUEST_BUDGET
) -> int:
    """Seconds between captures so `hours` of capturing stays within the daily budget."""
    if n_symbols < 1 or hours <= 0:
        raise ValueError("need at least one symbol and a positive number of hours")
    captures_allowed = daily_budget // n_symbols
    if captures_allowed < 1:
        raise ValueError(f"{n_symbols} symbols exceed the daily budget of {daily_budget}")
    return max(MIN_INTERVAL_SECONDS, math.ceil(hours * 3600 / captures_allowed))


def in_sleep_window(now: datetime, sleep: clock_time, wake: clock_time, tz: str) -> bool:
    """Is `now` inside the user's sleep window? Checks last night's and tonight's window."""
    local_today = now.astimezone(ZoneInfo(tz)).date()
    for night in (local_today - timedelta(days=1), local_today):
        start, end = sleep_window_utc(night, sleep, wake, tz)
        if start <= now < end:
            return True
    return False


def window_hours(sleep: clock_time, wake: clock_time) -> float:
    """Length of the sleep window in hours (ignoring DST nights)."""
    start = sleep.hour * 60 + sleep.minute
    end = wake.hour * 60 + wake.minute
    return ((end - start) % (24 * 60)) / 60


def main() -> None:
    from data_sources.market_data.twelve_data import TwelveDataProvider
    from ms_db.repositories import list_instruments
    from ms_db.session import new_session
    from worker.config import load_environment, optional, required
    from worker.jobs.overnight_capture import (
        FREE_TIER_CALLS,
        FREE_TIER_PERIOD_SECONDS,
        RateLimiter,
        capture_snapshots,
    )

    parser = argparse.ArgumentParser(description="Run the capture job on a schedule.")
    parser.add_argument("--always", action="store_true", help="ignore the sleep window")
    parser.add_argument("--interval", type=int, help="seconds between captures (overrides)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    load_environment()

    tz = optional("USER_TIMEZONE", "Europe/London")
    sleep = clock_time.fromisoformat(optional("SLEEP_START", "23:00"))
    wake = clock_time.fromisoformat(optional("WAKE_TIME", "07:00"))

    with new_session() as session:
        n_symbols = len(list_instruments(session))
    if n_symbols == 0:
        raise SystemExit("The watchlist is empty: run `make seed` first.")

    hours = 24.0 if args.always else window_hours(sleep, wake)
    interval = args.interval or interval_for_budget(n_symbols, hours)
    mode = "always" if args.always else f"sleep window {sleep:%H:%M}-{wake:%H:%M} {tz}"
    log.info(
        "scheduler started: %d instruments, every %ds (%s). Ctrl+C to stop.",
        n_symbols,
        interval,
        mode,
    )

    provider = TwelveDataProvider(required("TWELVE_DATA_API_KEY"))
    limiter = RateLimiter(FREE_TIER_CALLS, FREE_TIER_PERIOD_SECONDS)
    try:
        while True:
            now = datetime.now(UTC)
            if args.always or in_sleep_window(now, sleep, wake, tz):
                with new_session() as session:
                    capture_snapshots(session, provider, source="twelve_data", limiter=limiter)
            else:
                log.info("outside the sleep window, not capturing")
            time.sleep(interval)
    except KeyboardInterrupt:
        log.info("scheduler stopped")
    finally:
        provider.close()


if __name__ == "__main__":
    main()
