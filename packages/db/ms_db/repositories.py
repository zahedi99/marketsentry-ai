"""Repositories: the only code that reads or writes the database.

Callers pass domain models (market_core) in and get domain models back; ORM rows
never leave this module. Functions don't commit: the caller owns the transaction,
so a job can save many things and commit them together (or roll them all back).

Writes are idempotent (INSERT ... ON CONFLICT), so re-running a job never creates
duplicates: a requirement for worker jobs.
"""

from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from market_core.models import AssetClass, DailyClose, Instrument, PriceSnapshot
from ms_db.models import DailyCloseRow, InstrumentRow, PriceSnapshotRow


def _key(symbol: str) -> str:
    return symbol.strip().upper()


# --- instruments ----------------------------------------------------------------


def upsert_instrument(session: Session, instrument: Instrument) -> None:
    """Insert an instrument, or update its details if the symbol already exists."""
    values = {
        "symbol": instrument.symbol,
        "name": instrument.name,
        "asset_class": instrument.asset_class.value,
        "currency": instrument.currency,
    }
    stmt = insert(InstrumentRow).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[InstrumentRow.symbol],
        set_={k: stmt.excluded[k] for k in ("name", "asset_class", "currency")},
    )
    session.execute(stmt)


def get_instrument(session: Session, symbol: str) -> Instrument | None:
    row = session.scalars(select(InstrumentRow).where(InstrumentRow.symbol == _key(symbol))).first()
    if row is None:
        return None
    return Instrument(
        symbol=row.symbol,
        name=row.name,
        asset_class=AssetClass(row.asset_class),
        currency=row.currency,
    )


# --- daily closes ---------------------------------------------------------------


def save_daily_closes(session: Session, closes: Iterable[DailyClose], source: str) -> int:
    """Store closes, skipping any (symbol, day) already stored. Returns how many were new."""
    values = [
        {"symbol": _key(c.symbol), "day": c.day, "close": c.close, "source": source} for c in closes
    ]
    if not values:
        return 0
    stmt = (
        insert(DailyCloseRow)
        .values(values)
        .on_conflict_do_nothing(index_elements=[DailyCloseRow.symbol, DailyCloseRow.day])
        .returning(DailyCloseRow.id)
    )
    return len(session.execute(stmt).all())


def get_daily_closes(session: Session, symbol: str, start: date, end: date) -> list[DailyClose]:
    """Closes for one symbol with start <= day <= end, oldest first."""
    if start > end:
        raise ValueError(f"start date {start} is after end date {end}")
    rows = session.scalars(
        select(DailyCloseRow)
        .where(
            DailyCloseRow.symbol == _key(symbol),
            DailyCloseRow.day >= start,
            DailyCloseRow.day <= end,
        )
        .order_by(DailyCloseRow.day)
    )
    return [DailyClose(symbol=r.symbol, day=r.day, close=r.close) for r in rows]


# --- price snapshots ------------------------------------------------------------


def save_snapshot(session: Session, snapshot: PriceSnapshot, source: str) -> bool:
    """Store a snapshot. Returns False if this (symbol, observed_at) was already stored."""
    stmt = (
        insert(PriceSnapshotRow)
        .values(
            symbol=snapshot.symbol,
            observed_at=snapshot.observed_at,
            price=snapshot.price,
            volume=snapshot.volume,
            source=source,
        )
        .on_conflict_do_nothing(
            index_elements=[PriceSnapshotRow.symbol, PriceSnapshotRow.observed_at]
        )
        .returning(PriceSnapshotRow.id)
    )
    return session.execute(stmt).first() is not None


def latest_snapshots(
    session: Session, symbols: Sequence[str] | None = None
) -> dict[str, PriceSnapshot]:
    """The most recent stored snapshot per symbol (all symbols, or just those given)."""
    query = (
        select(PriceSnapshotRow)
        .ext(distinct_on(PriceSnapshotRow.symbol))  # Postgres DISTINCT ON (symbol)
        .order_by(PriceSnapshotRow.symbol, PriceSnapshotRow.observed_at.desc())
    )
    if symbols is not None:
        query = query.where(PriceSnapshotRow.symbol.in_([_key(s) for s in symbols]))
    return {
        row.symbol: PriceSnapshot(
            symbol=row.symbol,
            observed_at=row.observed_at,
            price=row.price,
            volume=row.volume,
        )
        for row in session.scalars(query)
    }
