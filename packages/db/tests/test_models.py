"""Schema tests: inspect the table definitions. No database needed."""

from sqlalchemy import Column, DateTime, Float, Numeric, String, Table, UniqueConstraint

from ms_db.models import Base, DailyCloseRow, InstrumentRow, PriceSnapshotRow


def table(name: str) -> Table:
    return Base.metadata.tables[name]


def unique_sets(t: Table) -> set[frozenset[str]]:
    """Column-name sets that must be unique together (constraints + unique columns)."""
    sets = {
        frozenset(c.name for c in con.columns)
        for con in t.constraints
        if isinstance(con, UniqueConstraint)
    }
    sets |= {frozenset([c.name]) for c in t.columns if c.unique}
    return sets


def fk_target(column: Column[object]) -> str:
    (fk,) = column.foreign_keys
    return fk.target_fullname


# --- overall --------------------------------------------------------------------


def test_tables() -> None:
    assert set(Base.metadata.tables) == {"instruments", "daily_closes", "price_snapshots"}


def test_classes_map_to_tables() -> None:
    assert InstrumentRow.__tablename__ == "instruments"
    assert DailyCloseRow.__tablename__ == "daily_closes"
    assert PriceSnapshotRow.__tablename__ == "price_snapshots"


def test_no_float_columns_anywhere() -> None:
    # Prices must stay exact: Numeric, never Float.
    for t in Base.metadata.tables.values():
        for c in t.columns:
            assert not isinstance(c.type, Float), f"{t.name}.{c.name} is Float"


def test_every_timestamp_is_timezone_aware() -> None:
    for t in Base.metadata.tables.values():
        for c in t.columns:
            if isinstance(c.type, DateTime):
                assert c.type.timezone, f"{t.name}.{c.name} is not timezone-aware"


# --- instruments ----------------------------------------------------------------


def test_instruments_columns() -> None:
    t = table("instruments")

    assert set(t.columns.keys()) == {"id", "symbol", "name", "asset_class", "currency"}
    assert t.c.id.primary_key
    assert all(not c.nullable for c in t.columns)


def test_instrument_symbol_is_unique() -> None:
    assert frozenset({"symbol"}) in unique_sets(table("instruments"))


def test_instrument_string_lengths() -> None:
    t = table("instruments")

    assert isinstance(t.c.symbol.type, String) and t.c.symbol.type.length == 20
    assert isinstance(t.c.currency.type, String) and t.c.currency.type.length == 3


# --- daily_closes ---------------------------------------------------------------


def test_daily_closes_columns() -> None:
    t = table("daily_closes")

    assert set(t.columns.keys()) == {"id", "symbol", "day", "close", "source"}
    assert t.c.id.primary_key
    assert all(not c.nullable for c in t.columns)


def test_daily_close_price_is_exact_numeric() -> None:
    close = table("daily_closes").c.close.type

    assert isinstance(close, Numeric)
    assert (close.precision, close.scale) == (20, 8)


def test_daily_closes_belong_to_an_instrument() -> None:
    assert fk_target(table("daily_closes").c.symbol) == "instruments.symbol"


def test_one_close_per_symbol_per_day() -> None:
    # Makes saving idempotent: re-running a job can't create duplicates.
    assert frozenset({"symbol", "day"}) in unique_sets(table("daily_closes"))


# --- price_snapshots ------------------------------------------------------------


def test_price_snapshots_columns() -> None:
    t = table("price_snapshots")

    assert set(t.columns.keys()) == {
        "id",
        "symbol",
        "observed_at",
        "price",
        "volume",
        "source",
        "captured_at",
    }
    assert t.c.id.primary_key


def test_snapshot_volume_is_optional_everything_else_required() -> None:
    t = table("price_snapshots")

    assert t.c.volume.nullable
    assert all(not c.nullable for c in t.columns if c.name != "volume")


def test_snapshot_price_is_exact_numeric() -> None:
    price = table("price_snapshots").c.price.type

    assert isinstance(price, Numeric)
    assert (price.precision, price.scale) == (20, 8)


def test_snapshots_belong_to_an_instrument() -> None:
    assert fk_target(table("price_snapshots").c.symbol) == "instruments.symbol"


def test_one_snapshot_per_symbol_per_moment() -> None:
    assert frozenset({"symbol", "observed_at"}) in unique_sets(table("price_snapshots"))


def test_captured_at_is_filled_in_by_the_database() -> None:
    # When WE stored it (provenance), as opposed to observed_at: when the price was quoted.
    assert table("price_snapshots").c.captured_at.server_default is not None
