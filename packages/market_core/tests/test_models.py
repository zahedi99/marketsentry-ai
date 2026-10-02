from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from market_core.models import AssetClass, Instrument, PriceSnapshot


def make_instrument(**overrides: Any) -> Instrument:
    """Build a valid Instrument; tests override only the field they care about."""
    fields: dict[str, Any] = {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "asset_class": AssetClass.EQUITY,
        "currency": "USD",
    }
    return Instrument(**(fields | overrides))


def make_snapshot(**overrides: Any) -> PriceSnapshot:
    """Build a valid PriceSnapshot; tests override only the field they care about."""
    fields: dict[str, Any] = {
        "symbol": "AAPL",
        "observed_at": datetime(2026, 10, 2, 20, 0, tzinfo=UTC),
        "price": Decimal("187.50"),
    }
    return PriceSnapshot(**(fields | overrides))


# --- Instrument ---------------------------------------------------------------


def test_instrument_valid() -> None:
    inst = make_instrument()

    assert inst.symbol == "AAPL"
    assert inst.name == "Apple Inc."
    assert inst.asset_class is AssetClass.EQUITY
    assert inst.currency == "USD"


def test_instrument_asset_class_accepts_plain_string() -> None:
    # Data from the DB or an API arrives as plain strings, not enum members.
    assert make_instrument(asset_class="crypto").asset_class is AssetClass.CRYPTO


def test_instrument_symbol_is_normalised() -> None:
    assert make_instrument(symbol="  aapl ").symbol == "AAPL"


@pytest.mark.parametrize("symbol", ["", "   "])
def test_instrument_rejects_blank_symbol(symbol: str) -> None:
    with pytest.raises(ValidationError):
        make_instrument(symbol=symbol)


@pytest.mark.parametrize("currency", ["usd", "US", "USDT", "U5D"])
def test_instrument_rejects_bad_currency(currency: str) -> None:
    with pytest.raises(ValidationError):
        make_instrument(currency=currency)


def test_instrument_rejects_unknown_asset_class() -> None:
    with pytest.raises(ValidationError):
        make_instrument(asset_class="bond")


def test_instrument_is_frozen() -> None:
    inst = make_instrument()

    with pytest.raises(ValidationError):
        inst.name = "Something else"  # type: ignore[misc]


def test_instrument_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        make_instrument(sector="Technology")


# --- PriceSnapshot ------------------------------------------------------------


def test_snapshot_valid() -> None:
    snap = make_snapshot(volume=1_000)

    assert snap.symbol == "AAPL"
    assert snap.price == Decimal("187.50")
    assert snap.volume == 1_000


def test_snapshot_volume_defaults_to_none() -> None:
    assert make_snapshot().volume is None


def test_snapshot_symbol_is_normalised() -> None:
    assert make_snapshot(symbol=" msft").symbol == "MSFT"


def test_snapshot_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError):
        make_snapshot(observed_at=datetime(2026, 10, 2, 20, 0))  # noqa: DTZ001 - deliberately naive


def test_snapshot_converts_to_utc_keeping_the_same_instant() -> None:
    tokyo_9am = datetime(2026, 10, 2, 9, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    snap = make_snapshot(observed_at=tokyo_9am)

    assert snap.observed_at.tzinfo is UTC
    assert snap.observed_at == datetime(2026, 10, 2, 0, 0, tzinfo=UTC)  # 09:00 JST == 00:00 UTC
    assert snap.observed_at == tokyo_9am  # same moment in time


def test_snapshot_price_keeps_exact_decimal() -> None:
    # A string input becomes an exact Decimal, with no float rounding along the way.
    assert make_snapshot(price="0.1").price + Decimal("0.2") == Decimal("0.3")


@pytest.mark.parametrize("price", [0, -1, "-0.01"])
def test_snapshot_rejects_non_positive_price(price: Any) -> None:
    with pytest.raises(ValidationError):
        make_snapshot(price=price)


def test_snapshot_rejects_negative_volume() -> None:
    with pytest.raises(ValidationError):
        make_snapshot(volume=-1)
