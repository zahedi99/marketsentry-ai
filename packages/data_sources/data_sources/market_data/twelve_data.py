"""Twelve Data adapter (https://twelvedata.com/docs) for the MarketDataProvider contract.

Response facts this adapter relies on (verified against the live API, 2026-10-06):
- prices arrive as strings, so they convert to Decimal exactly;
- `end_date` is EXCLUSIVE, while our contract is inclusive, so we request end + 1 day;
- an unknown symbol is HTTP 404; a range with no trading days is HTTP 400 "No data is
  available", which we treat as an empty result, not an error;
- FX quotes have no volume.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from pydantic import ValidationError

from data_sources.market_data.base import (
    DailyClose,
    ProviderError,
    RateLimitError,
    UnknownSymbolError,
)
from market_core.models import PriceSnapshot

BASE_URL = "https://api.twelvedata.com"
_NO_DATA_MESSAGE = "No data is available"


class _NoData(Exception):
    """Internal signal: the request was valid but the range contained no data."""


class TwelveDataProvider:
    """Market data from Twelve Data. The API key travels in a header, never in the URL."""

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Twelve Data API key is empty: set TWELVE_DATA_API_KEY in .env")
        # Tests inject a client with a mock transport; production builds a real one.
        self._client = client or httpx.Client(base_url=BASE_URL, timeout=timeout)
        self._headers = {"Authorization": f"apikey {api_key.strip()}"}

    def close(self) -> None:
        """Release the underlying HTTP connections."""
        self._client.close()

    def daily_closes(self, symbol: str, start: date, end: date) -> list[DailyClose]:
        if start > end:
            raise ValueError(f"start date {start} is after end date {end}")
        try:
            body = self._get(
                "/time_series",
                symbol=symbol,
                interval="1day",
                start_date=start.isoformat(),
                end_date=(end + timedelta(days=1)).isoformat(),  # API end is exclusive
                order="ASC",
            )
        except _NoData:
            return []

        try:
            closes = [
                DailyClose(
                    symbol=symbol.strip().upper(),
                    day=date.fromisoformat(row["datetime"][:10]),
                    close=Decimal(row["close"]),
                )
                for row in body["values"]
            ]
        except (KeyError, TypeError, ValueError, InvalidOperation, ValidationError) as exc:
            raise ProviderError(f"unexpected time_series response for {symbol}") from exc
        return sorted(closes, key=lambda c: c.day)

    def latest_snapshot(self, symbol: str) -> PriceSnapshot:
        try:
            body = self._get("/quote", symbol=symbol)
        except _NoData as exc:
            raise UnknownSymbolError(f"no quote available for {symbol}") from exc

        try:
            unix_time = body.get("last_quote_at") or body["timestamp"]
            volume = body.get("volume")
            return PriceSnapshot(
                symbol=symbol,
                observed_at=datetime.fromtimestamp(int(unix_time), tz=UTC),
                price=Decimal(body["close"]),
                volume=int(volume) if volume else None,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation, ValidationError) as exc:
            raise ProviderError(f"unexpected quote response for {symbol}") from exc

    def _get(self, path: str, **params: str) -> dict[str, Any]:
        """GET a Twelve Data endpoint and turn its error formats into our error types."""
        try:
            response = self._client.get(path, params=params, headers=self._headers)
        except httpx.HTTPError as exc:
            raise ProviderError(f"could not reach Twelve Data: {type(exc).__name__}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            status = response.status_code
            raise ProviderError(f"Twelve Data returned non-JSON (HTTP {status})") from exc
        if not isinstance(body, dict):
            raise ProviderError("Twelve Data returned an unexpected payload")

        if body.get("status") == "error" or response.status_code >= 400:
            code = body.get("code", response.status_code)
            message = str(body.get("message", ""))
            if code == 404:
                raise UnknownSymbolError(f"unknown symbol: {params.get('symbol')}")
            if code == 429:
                raise RateLimitError("Twelve Data rate limit reached")
            if code == 400 and message.startswith(_NO_DATA_MESSAGE):
                raise _NoData
            raise ProviderError(f"Twelve Data error {code}: {message[:200]}")

        return body
