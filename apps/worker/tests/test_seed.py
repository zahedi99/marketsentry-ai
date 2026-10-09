"""Seed tests: run against the test database (fixtures from ms_db.testing)."""

from sqlalchemy.orm import Session

from market_core.models import AssetClass
from ms_db.repositories import list_instruments
from worker.seed import DEFAULT_WATCHLIST, seed_watchlist


def test_watchlist_covers_every_asset_class() -> None:
    assert {i.asset_class for i in DEFAULT_WATCHLIST} == set(AssetClass)


def test_watchlist_symbols_are_unique() -> None:
    symbols = [i.symbol for i in DEFAULT_WATCHLIST]
    assert len(symbols) == len(set(symbols))


def test_seed_inserts_the_watchlist(session: Session) -> None:
    count = seed_watchlist(session)

    assert count == len(DEFAULT_WATCHLIST)
    assert {i.symbol for i in list_instruments(session)} == {i.symbol for i in DEFAULT_WATCHLIST}


def test_seeding_twice_does_not_duplicate(session: Session) -> None:
    seed_watchlist(session)
    seed_watchlist(session)

    assert len(list_instruments(session)) == len(DEFAULT_WATCHLIST)
