"""Seed the default watchlist into the database. Run with `make seed`.

Idempotent: running it again updates names/currencies but never duplicates instruments.
All symbols were checked against the Twelve Data free tier (2026-10-09); the crypto
pairs also stream live from Binance (`make live`).
"""

from sqlalchemy.orm import Session

from market_core.models import AssetClass, Instrument
from ms_db.repositories import upsert_instrument
from ms_db.session import new_session

DEFAULT_WATCHLIST: tuple[Instrument, ...] = (
    Instrument(symbol="AAPL", name="Apple Inc.", asset_class=AssetClass.EQUITY, currency="USD"),
    Instrument(
        symbol="MSFT", name="Microsoft Corporation", asset_class=AssetClass.EQUITY, currency="USD"
    ),
    Instrument(
        symbol="NVDA", name="NVIDIA Corporation", asset_class=AssetClass.EQUITY, currency="USD"
    ),
    # SPY (an ETF tracking the S&P 500) stands in for the index on the free tier.
    Instrument(
        symbol="SPY", name="SPDR S&P 500 ETF Trust", asset_class=AssetClass.INDEX, currency="USD"
    ),
    Instrument(
        symbol="EUR/USD", name="Euro / US Dollar", asset_class=AssetClass.FX, currency="USD"
    ),
    Instrument(
        symbol="GBP/USD",
        name="British Pound / US Dollar",
        asset_class=AssetClass.FX,
        currency="USD",
    ),
    Instrument(
        symbol="BTC/USD", name="Bitcoin / US Dollar", asset_class=AssetClass.CRYPTO, currency="USD"
    ),
    Instrument(
        symbol="ETH/USD", name="Ether / US Dollar", asset_class=AssetClass.CRYPTO, currency="USD"
    ),
    Instrument(
        symbol="XAU/USD", name="Gold / US Dollar", asset_class=AssetClass.COMMODITY, currency="USD"
    ),
)


def seed_watchlist(
    session: Session, instruments: tuple[Instrument, ...] = DEFAULT_WATCHLIST
) -> int:
    """Upsert the instruments. Doesn't commit: the caller owns the transaction."""
    for instrument in instruments:
        upsert_instrument(session, instrument)
    return len(instruments)


def main() -> None:
    with new_session() as session:
        count = seed_watchlist(session)
        session.commit()
    symbols = ", ".join(i.symbol for i in DEFAULT_WATCHLIST)
    print(f"Seeded {count} instruments: {symbols}")


if __name__ == "__main__":
    main()
