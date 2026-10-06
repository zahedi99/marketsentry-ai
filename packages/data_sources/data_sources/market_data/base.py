from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable

from pydantic import Field

from market_core.models import PriceSnapshot, StrictModel


class DailyClose(StrictModel):
    symbol: str
    day: date
    close: Decimal = Field(gt=0)


class ProviderError(Exception):
    """Base class for all provider errors."""

    pass


class UnknownSymbolError(ProviderError):
    """Raised when a symbol is not found in the provider's data."""

    pass


class RateLimitError(ProviderError):
    """Raised when the provider refuses a request because too many were made."""


@runtime_checkable
class MarketDataProvider(Protocol):
    def daily_closes(self, symbol: str, start: date, end: date) -> list[DailyClose]:
        """Returns daily closing prices for a given symbol and date range."""
        ...

    def latest_snapshot(self, symbol: str) -> PriceSnapshot:
        """Returns the latest price snapshot for a given symbol."""
        ...
