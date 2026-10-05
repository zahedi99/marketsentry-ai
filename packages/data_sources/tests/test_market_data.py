from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from data_sources.market_data.base import (
    DailyClose,
    MarketDataProvider,
    ProviderError,
    UnknownSymbolError,
)
from data_sources.market_data.fake import FakeMarketDataProvider
from market_core.models import PriceSnapshot


def close(day: int, price: str, symbol: str = "AAPL") -> DailyClose:
    return DailyClose(symbol=symbol, day=date(2026, 10, day), close=Decimal(price))


def snapshot(price: str, symbol: str = "AAPL") -> PriceSnapshot:
    at = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)
    return PriceSnapshot(symbol=symbol, observed_at=at, price=Decimal(price))


# --- DailyClose -----------------------------------------------------------------


def test_daily_close_rejects_non_positive_price() -> None:
    with pytest.raises(ValueError):
        close(1, "0")


def test_daily_close_is_frozen() -> None:
    c = close(1, "100")
    with pytest.raises(ValueError):
        c.close = Decimal("1")  # type: ignore[misc]


# --- errors ---------------------------------------------------------------------


def test_unknown_symbol_is_a_provider_error() -> None:
    # Callers can catch every provider failure with one `except ProviderError`.
    assert issubclass(UnknownSymbolError, ProviderError)


# --- the fake satisfies the interface --------------------------------------------


def test_fake_is_a_market_data_provider() -> None:
    assert isinstance(FakeMarketDataProvider(), MarketDataProvider)


def test_code_written_against_the_interface_works_with_the_fake() -> None:
    def latest_close(provider: MarketDataProvider, symbol: str) -> Decimal:
        closes = provider.daily_closes(symbol, date(2026, 10, 1), date(2026, 10, 31))
        return closes[-1].close

    fake = FakeMarketDataProvider()
    fake.add_closes([close(1, "100"), close(2, "101")])

    assert latest_close(fake, "AAPL") == Decimal("101")


# --- daily_closes ---------------------------------------------------------------


def test_daily_closes_returns_range_inclusive() -> None:
    fake = FakeMarketDataProvider()
    fake.add_closes([close(d, str(100 + d)) for d in range(1, 11)])

    result = fake.daily_closes("AAPL", date(2026, 10, 3), date(2026, 10, 5))

    assert [c.day.day for c in result] == [3, 4, 5]


def test_daily_closes_are_sorted_oldest_first() -> None:
    fake = FakeMarketDataProvider()
    fake.add_closes([close(5, "105"), close(1, "101"), close(3, "103")])

    result = fake.daily_closes("AAPL", date(2026, 10, 1), date(2026, 10, 31))

    assert [c.day.day for c in result] == [1, 3, 5]


def test_daily_closes_only_for_the_requested_symbol() -> None:
    fake = FakeMarketDataProvider()
    fake.add_closes([close(1, "100"), close(1, "400", symbol="MSFT")])

    result = fake.daily_closes("MSFT", date(2026, 10, 1), date(2026, 10, 31))

    assert [c.close for c in result] == [Decimal("400")]


def test_daily_closes_symbol_is_case_insensitive() -> None:
    fake = FakeMarketDataProvider()
    fake.add_closes([close(1, "100")])

    assert len(fake.daily_closes(" aapl ", date(2026, 10, 1), date(2026, 10, 31))) == 1


def test_daily_closes_known_symbol_but_empty_range_is_empty_list() -> None:
    fake = FakeMarketDataProvider()
    fake.add_closes([close(1, "100")])

    assert fake.daily_closes("AAPL", date(2026, 10, 20), date(2026, 10, 25)) == []


def test_daily_closes_unknown_symbol_raises() -> None:
    with pytest.raises(UnknownSymbolError):
        FakeMarketDataProvider().daily_closes("NOPE", date(2026, 10, 1), date(2026, 10, 31))


def test_daily_closes_rejects_start_after_end() -> None:
    fake = FakeMarketDataProvider()
    fake.add_closes([close(1, "100")])

    with pytest.raises(ValueError):
        fake.daily_closes("AAPL", date(2026, 10, 31), date(2026, 10, 1))


# --- latest_snapshot ------------------------------------------------------------


def test_latest_snapshot_returns_what_was_set() -> None:
    fake = FakeMarketDataProvider()
    fake.set_snapshot(snapshot("187.50"))

    assert fake.latest_snapshot("AAPL") == snapshot("187.50")


def test_latest_snapshot_replaces_older_value() -> None:
    fake = FakeMarketDataProvider()
    fake.set_snapshot(snapshot("187.50"))
    fake.set_snapshot(snapshot("190.00"))

    assert fake.latest_snapshot("aapl").price == Decimal("190.00")


def test_latest_snapshot_unknown_symbol_raises() -> None:
    with pytest.raises(UnknownSymbolError):
        FakeMarketDataProvider().latest_snapshot("NOPE")
