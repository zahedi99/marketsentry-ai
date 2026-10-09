"""Capture job tests. The provider is the in-memory fake (no network); the database is
the rolled-back test database (fixtures from ms_db.testing)."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from data_sources.market_data.base import DailyClose, RateLimitError
from data_sources.market_data.fake import FakeMarketDataProvider
from market_core.models import PriceSnapshot
from ms_db.repositories import latest_snapshots
from worker.jobs.overnight_capture import CaptureReport, RateLimiter, capture_snapshots
from worker.seed import DEFAULT_WATCHLIST, seed_watchlist

T0 = datetime(2026, 10, 9, 2, 0, tzinfo=UTC)
SYMBOLS = [i.symbol for i in DEFAULT_WATCHLIST]


def provider_with_prices(at: datetime = T0, skip: tuple[str, ...] = ()) -> FakeMarketDataProvider:
    fake = FakeMarketDataProvider()
    for n, symbol in enumerate(SYMBOLS, start=1):
        if symbol not in skip:
            fake.set_snapshot(PriceSnapshot(symbol=symbol, observed_at=at, price=Decimal(n * 10)))
    return fake


# --- RateLimiter ----------------------------------------------------------------


class FakeClock:
    """A clock that only moves when told to, so rate-limit tests run instantly."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_limiter_allows_max_calls_without_waiting() -> None:
    clock = FakeClock()
    limiter = RateLimiter(3, 60, clock=clock, sleep=clock.sleep)

    for _ in range(3):
        limiter.wait()

    assert clock.sleeps == []


def test_limiter_waits_when_window_is_full() -> None:
    clock = FakeClock()
    limiter = RateLimiter(3, 60, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        limiter.wait()
    clock.now = 10.0

    limiter.wait()  # 4th call: must wait until the first call is 60s old

    assert clock.sleeps == [50.0]


def test_limiter_does_not_wait_once_window_has_passed() -> None:
    clock = FakeClock()
    limiter = RateLimiter(3, 60, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        limiter.wait()
    clock.now = 61.0

    limiter.wait()

    assert clock.sleeps == []


@pytest.mark.parametrize(("calls", "period"), [(0, 60), (3, 0)])
def test_limiter_rejects_nonsense_settings(calls: int, period: float) -> None:
    with pytest.raises(ValueError):
        RateLimiter(calls, period)


# --- capture_snapshots ----------------------------------------------------------


def test_captures_every_watchlist_instrument(session: Session) -> None:
    seed_watchlist(session)

    report = capture_snapshots(session, provider_with_prices(), source="test")

    assert sorted(report.saved) == sorted(SYMBOLS)
    assert report.failed == {}
    stored = latest_snapshots(session)
    assert set(stored) == set(SYMBOLS)
    assert stored["AAPL"].price == Decimal("10")


def test_rerun_with_same_prices_stores_nothing_new(session: Session) -> None:
    seed_watchlist(session)
    capture_snapshots(session, provider_with_prices(), source="test")

    report = capture_snapshots(session, provider_with_prices(), source="test")

    assert report.saved == []
    assert sorted(report.already_stored) == sorted(SYMBOLS)


def test_newer_prices_are_saved(session: Session) -> None:
    seed_watchlist(session)
    capture_snapshots(session, provider_with_prices(), source="test")

    later = T0 + timedelta(minutes=15)
    report = capture_snapshots(session, provider_with_prices(at=later), source="test")

    assert sorted(report.saved) == sorted(SYMBOLS)
    assert latest_snapshots(session)["AAPL"].observed_at == later


def test_one_failing_symbol_does_not_stop_the_others(session: Session) -> None:
    seed_watchlist(session)
    provider = provider_with_prices(skip=("NVDA",))  # fake raises UnknownSymbolError

    report = capture_snapshots(session, provider, source="test")

    assert set(report.failed) == {"NVDA"}
    assert len(report.saved) == len(SYMBOLS) - 1
    assert "NVDA" not in latest_snapshots(session)


class RateLimitedProvider(FakeMarketDataProvider):
    def latest_snapshot(self, symbol: str) -> PriceSnapshot:
        raise RateLimitError("too many requests")

    def daily_closes(self, symbol: str, start: object, end: object) -> list[DailyClose]:
        return []


def test_provider_rate_limit_is_reported(session: Session) -> None:
    seed_watchlist(session)

    report = capture_snapshots(session, RateLimitedProvider(), source="test")

    assert set(report.failed) == set(SYMBOLS)
    assert all("rate limited" in reason for reason in report.failed.values())


def test_waits_on_the_limiter_once_per_instrument(session: Session) -> None:
    seed_watchlist(session)
    clock = FakeClock()
    limiter = RateLimiter(3, 60, clock=clock, sleep=clock.sleep)

    capture_snapshots(session, provider_with_prices(), source="test", limiter=limiter)

    # 8 instruments at 3 per minute: waits before the 4th and the 7th call.
    assert len(clock.sleeps) == 2


def test_empty_watchlist_does_nothing(session: Session) -> None:
    report = capture_snapshots(session, provider_with_prices(), source="test")

    assert report == CaptureReport()


def test_summary() -> None:
    report = CaptureReport(saved=["A", "B"], already_stored=["C"], failed={"D": "boom"})

    assert report.summary() == "saved 2, already stored 1, failed 1"
