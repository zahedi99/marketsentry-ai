import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from market_core.models import AssetClass, Instrument, PriceSnapshot
from worker.jobs.live_stream import Throttle, stream_to_database

T0 = datetime(2026, 10, 9, 13, 0, tzinfo=UTC)
BTC = Instrument(symbol="BTC/USD", name="Bitcoin", asset_class=AssetClass.CRYPTO, currency="USD")
AAPL = Instrument(symbol="AAPL", name="Apple", asset_class=AssetClass.EQUITY, currency="USD")


class ScriptedStream:
    """A streaming provider that yields a fixed list of snapshots, then waits forever."""

    def __init__(
        self,
        name: str,
        asset_class: AssetClass,
        snaps: Sequence[PriceSnapshot],
    ) -> None:
        self.name = name
        self._asset_class = asset_class
        self._snaps = list(snaps)

    def supports(self, instrument: Instrument) -> bool:
        return instrument.asset_class is self._asset_class

    async def _gen(self) -> AsyncIterator[PriceSnapshot]:
        for snap in self._snaps:
            yield snap
        await asyncio.Event().wait()  # a real stream never ends

    def stream(self, instruments: Sequence[Instrument]) -> AsyncIterator[PriceSnapshot]:
        return self._gen()


def snap(symbol: str, price: str, seconds: int = 0) -> PriceSnapshot:
    return PriceSnapshot(
        symbol=symbol, observed_at=T0 + timedelta(seconds=seconds), price=Decimal(price)
    )


# --- Throttle -------------------------------------------------------------------


def test_throttle_lets_first_through_then_blocks_until_interval() -> None:
    throttle = Throttle(2.0)

    assert throttle.ready(snap("BTC/USD", "1", seconds=0))
    assert not throttle.ready(snap("BTC/USD", "2", seconds=1))
    assert throttle.ready(snap("BTC/USD", "3", seconds=2))


def test_throttle_is_per_symbol() -> None:
    throttle = Throttle(2.0)

    assert throttle.ready(snap("BTC/USD", "1"))
    assert throttle.ready(snap("ETH/USD", "1"))


# --- stream_to_database ---------------------------------------------------------


async def test_saves_snapshots_from_all_providers_with_their_source() -> None:
    saved: list[tuple[str, str]] = []

    def save(snapshot: PriceSnapshot, source: str) -> bool:
        saved.append((snapshot.symbol, source))
        return True

    crypto = ScriptedStream("binance", AssetClass.CRYPTO, [snap("BTC/USD", "83000")])
    stocks = ScriptedStream("finnhub", AssetClass.EQUITY, [snap("AAPL", "340")])

    count = await stream_to_database([crypto, stocks], [BTC, AAPL], save, Throttle(0), stop_after=2)

    assert count == 2
    assert sorted(saved) == [("AAPL", "finnhub"), ("BTC/USD", "binance")]


async def test_throttle_drops_bursts() -> None:
    # One update per second of market time; a 2s throttle keeps every other one.
    saved: list[Decimal] = []

    def save(snapshot: PriceSnapshot, source: str) -> bool:
        saved.append(snapshot.price)
        return True

    burst = [snap("BTC/USD", str(n), seconds=n) for n in range(1, 7)]
    stream = ScriptedStream("binance", AssetClass.CRYPTO, burst)

    await stream_to_database([stream], [BTC], save, Throttle(2.0), stop_after=3)

    assert saved == [Decimal(1), Decimal(3), Decimal(5)]


async def test_duplicates_are_not_counted() -> None:
    def save(snapshot: PriceSnapshot, source: str) -> bool:
        return snapshot.price != Decimal("1")  # pretend price 1 was already stored

    snaps = [snap("BTC/USD", "1"), snap("BTC/USD", "2", 5)]
    stream = ScriptedStream("binance", AssetClass.CRYPTO, snaps)

    count = await stream_to_database([stream], [BTC], save, Throttle(0), stop_after=1)

    assert count == 1


async def test_no_supporting_provider_returns_immediately() -> None:
    stream = ScriptedStream("binance", AssetClass.CRYPTO, [])

    def save(snapshot: PriceSnapshot, source: str) -> bool:
        raise AssertionError("should not save")

    assert await stream_to_database([stream], [AAPL], save, Throttle(0)) == 0
