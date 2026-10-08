"""Repository tests against a real (test) Postgres. See conftest.py."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from market_core.models import AssetClass, DailyClose, Instrument, PriceSnapshot
from ms_db.models import PriceSnapshotRow
from ms_db.repositories import (
    get_daily_closes,
    get_instrument,
    latest_snapshots,
    save_daily_closes,
    save_snapshot,
    upsert_instrument,
)

T0 = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)


def add_instrument(session: Session, symbol: str = "AAPL") -> None:
    upsert_instrument(
        session,
        Instrument(symbol=symbol, name=f"{symbol} Inc.", asset_class="equity", currency="USD"),
    )


def close(day: int, price: str, symbol: str = "AAPL") -> DailyClose:
    return DailyClose(symbol=symbol, day=date(2026, 10, day), close=Decimal(price))


def snapshot(price: str, at: datetime = T0, symbol: str = "AAPL") -> PriceSnapshot:
    return PriceSnapshot(symbol=symbol, observed_at=at, price=Decimal(price), volume=1000)


# --- instruments ----------------------------------------------------------------


def test_upsert_then_get_instrument(session: Session) -> None:
    add_instrument(session)

    inst = get_instrument(session, " aapl ")

    assert inst is not None
    assert (inst.symbol, inst.name, inst.asset_class, inst.currency) == (
        "AAPL",
        "AAPL Inc.",
        AssetClass.EQUITY,
        "USD",
    )


def test_upsert_updates_existing_instrument(session: Session) -> None:
    add_instrument(session)
    upsert_instrument(
        session, Instrument(symbol="AAPL", name="Apple", asset_class="equity", currency="USD")
    )

    inst = get_instrument(session, "AAPL")

    assert inst is not None and inst.name == "Apple"


def test_unknown_instrument_is_none(session: Session) -> None:
    assert get_instrument(session, "NOPE") is None


# --- daily closes ---------------------------------------------------------------


def test_save_and_load_daily_closes(session: Session) -> None:
    add_instrument(session)

    saved = save_daily_closes(session, [close(2, "101.5"), close(1, "100")], source="test")
    loaded = get_daily_closes(session, "aapl", date(2026, 10, 1), date(2026, 10, 31))

    assert saved == 2
    assert [(c.day.day, c.close) for c in loaded] == [(1, Decimal("100")), (2, Decimal("101.5"))]


def test_prices_round_trip_exactly(session: Session) -> None:
    add_instrument(session)
    save_daily_closes(session, [close(1, "338.39999")], source="test")

    (loaded,) = get_daily_closes(session, "AAPL", date(2026, 10, 1), date(2026, 10, 1))

    assert loaded.close == Decimal("338.39999")


def test_saving_closes_twice_is_idempotent(session: Session) -> None:
    add_instrument(session)
    save_daily_closes(session, [close(1, "100"), close(2, "101")], source="test")

    again = save_daily_closes(session, [close(2, "101"), close(3, "102")], source="test")
    loaded = get_daily_closes(session, "AAPL", date(2026, 10, 1), date(2026, 10, 31))

    assert again == 1  # only day 3 was new
    assert [c.day.day for c in loaded] == [1, 2, 3]


def test_saving_no_closes_is_zero(session: Session) -> None:
    assert save_daily_closes(session, [], source="test") == 0


def test_daily_closes_range_is_inclusive(session: Session) -> None:
    add_instrument(session)
    save_daily_closes(session, [close(d, "100") for d in range(1, 8)], source="test")

    loaded = get_daily_closes(session, "AAPL", date(2026, 10, 3), date(2026, 10, 5))

    assert [c.day.day for c in loaded] == [3, 4, 5]


def test_daily_closes_rejects_start_after_end(session: Session) -> None:
    with pytest.raises(ValueError):
        get_daily_closes(session, "AAPL", date(2026, 10, 5), date(2026, 10, 1))


def test_close_for_unknown_instrument_is_rejected(session: Session) -> None:
    # The foreign key: no prices for instruments we don't track.
    with pytest.raises(IntegrityError):
        save_daily_closes(session, [close(1, "100", symbol="AAPLL")], source="test")


# --- snapshots ------------------------------------------------------------------


def test_save_snapshot_and_read_latest(session: Session) -> None:
    add_instrument(session)

    assert save_snapshot(session, snapshot("187.50"), source="test") is True
    latest = latest_snapshots(session)

    assert latest["AAPL"].price == Decimal("187.50")
    assert latest["AAPL"].observed_at == T0
    assert latest["AAPL"].volume == 1000


def test_saving_same_snapshot_twice_is_idempotent(session: Session) -> None:
    add_instrument(session)
    save_snapshot(session, snapshot("187.50"), source="test")

    assert save_snapshot(session, snapshot("187.50"), source="test") is False
    count = session.scalar(select(func.count()).select_from(PriceSnapshotRow))
    assert count == 1


def test_latest_snapshot_is_the_most_recent_per_symbol(session: Session) -> None:
    add_instrument(session, "AAPL")
    add_instrument(session, "MSFT")
    save_snapshot(session, snapshot("190", at=T0 + timedelta(hours=2)), source="test")
    save_snapshot(session, snapshot("187", at=T0), source="test")  # older, saved later
    save_snapshot(session, snapshot("400", symbol="MSFT"), source="test")

    latest = latest_snapshots(session)

    prices = {symbol: snap.price for symbol, snap in latest.items()}
    assert prices == {"AAPL": Decimal("190"), "MSFT": Decimal("400")}


def test_latest_snapshots_filtered_by_symbol(session: Session) -> None:
    add_instrument(session, "AAPL")
    add_instrument(session, "MSFT")
    save_snapshot(session, snapshot("187"), source="test")
    save_snapshot(session, snapshot("400", symbol="MSFT"), source="test")

    assert set(latest_snapshots(session, ["msft"])) == {"MSFT"}


def test_captured_at_is_set_by_the_database(session: Session) -> None:
    add_instrument(session)
    save_snapshot(session, snapshot("187"), source="test")

    row = session.scalars(select(PriceSnapshotRow)).one()

    assert row.captured_at is not None
    assert row.captured_at.tzinfo is not None
    assert row.source == "test"
