from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from market_core.models import StrictModel


def _to_utc(d: date, t: time, tz: str) -> datetime:
    """Convert a date and time in a given timezone to a UTC datetime."""
    tzinfo = ZoneInfo(tz)
    local_dt = datetime.combine(d, t, tzinfo=tzinfo)
    return local_dt.astimezone(UTC)


def sleep_window_utc(on_date: date, sleep: time, wake: time, tz: str) -> tuple[datetime, datetime]:
    """The user's sleep window as UTC (start, end).

    Wake is the next day if it's earlier on the clock.
    """
    wake_date = on_date
    if sleep == wake:
        raise ValueError("sleep and wake times cannot be the same")
    if wake < sleep:
        wake_date = on_date + timedelta(days=1)
    return _to_utc(on_date, sleep, tz), _to_utc(wake_date, wake, tz)


class Market(StrictModel):
    code: str
    timezone: str
    open: time
    close: time


NYSE = Market(code="NYSE", timezone="America/New_York", open=time(9, 30), close=time(16, 0))
LSE = Market(code="LSE", timezone="Europe/London", open=time(8, 0), close=time(16, 30))
TSE = Market(code="TSE", timezone="Asia/Tokyo", open=time(9, 0), close=time(15, 30))


def session_utc(market: Market, day: date) -> tuple[datetime, datetime] | None:
    """The market session for a given day as UTC (start, end).

    Returns None if the market is closed on that day.
    """
    if day.weekday() >= 5:  # Saturday or Sunday
        return None
    return _to_utc(day, market.open, market.timezone), _to_utc(day, market.close, market.timezone)
