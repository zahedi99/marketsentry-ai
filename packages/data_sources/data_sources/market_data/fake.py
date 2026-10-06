from collections.abc import Iterable
from datetime import date

from data_sources.market_data.base import DailyClose, UnknownSymbolError
from market_core.models import PriceSnapshot


def _key(symbol: str) -> str:
    return symbol.upper().strip()


class FakeMarketDataProvider:
    """in-memory provider for tests: returns exactly the data you give it"""

    def __init__(self) -> None:
        self._closes: dict[str, list[DailyClose]] = {}
        self._snapshots: dict[str, PriceSnapshot] = {}

    def add_closes(self, closes: Iterable[DailyClose]) -> None:
        for c in closes:
            self._closes.setdefault(_key(c.symbol), []).append(c)

    def set_snapshot(self, snapshot: PriceSnapshot) -> None:
        self._snapshots[_key(snapshot.symbol)] = snapshot

    def daily_closes(self, symbol: str, start: date, end: date) -> list[DailyClose]:
        if start > end:
            raise ValueError(f"start date {start} is after end date {end}")
        key = _key(symbol)
        if key not in self._closes:
            raise UnknownSymbolError(f"symbol {symbol} not found")
        return sorted((c for c in self._closes[key] if start <= c.day <= end), key=lambda c: c.day)

    def latest_snapshot(self, symbol: str) -> PriceSnapshot:
        key = _key(symbol)
        if key not in self._snapshots:
            raise UnknownSymbolError(f"symbol {symbol} not found")
        return self._snapshots[key]
