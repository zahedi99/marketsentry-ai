"""Finnhub WebSocket: live US stock trades on the free tier (needs FINNHUB_API_KEY).

Trades only arrive while the US market is open (14:30-21:00 London time); outside those
hours the connection stays quiet. Finnhub requires the API key in the URL, so the URL is
never logged (reconnecting_stream logs only the provider name).

Message shapes follow Finnhub's documentation; verify live once a key is configured.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from data_sources.streaming.base import (
    Connector,
    Sleep,
    WebSocketLike,
    default_connector,
    reconnecting_stream,
)
from market_core.models import AssetClass, Instrument, PriceSnapshot

BASE_URL = "wss://ws.finnhub.io?token="


def parse_trades(raw: str | bytes, symbols: set[str]) -> list[PriceSnapshot]:
    """A trade message can batch many trades: keep the latest one per symbol."""
    try:
        message = json.loads(raw)
        if message.get("type") != "trade":
            return []  # pings and other housekeeping messages
        latest: dict[str, PriceSnapshot] = {}
        for trade in message["data"]:
            symbol = trade["s"]
            if symbol not in symbols:
                continue
            snapshot = PriceSnapshot(
                symbol=symbol,
                observed_at=datetime.fromtimestamp(int(trade["t"]) / 1000, tz=UTC),
                price=Decimal(str(trade["p"])),
            )
            if symbol not in latest or snapshot.observed_at >= latest[symbol].observed_at:
                latest[symbol] = snapshot
        return list(latest.values())
    except (ValueError, KeyError, TypeError):
        return []


class FinnhubStream:
    name = "finnhub"

    def __init__(
        self,
        api_key: str,
        *,
        connector: Connector = default_connector,
        sleep: Sleep = asyncio.sleep,
        max_backoff: float = 30.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Finnhub API key is empty: set FINNHUB_API_KEY in .env")
        self._api_key = api_key.strip()
        self._connector = connector
        self._sleep = sleep
        self._max_backoff = max_backoff

    def supports(self, instrument: Instrument) -> bool:
        return instrument.asset_class in (AssetClass.EQUITY, AssetClass.INDEX)

    def stream(self, instruments: Sequence[Instrument]) -> AsyncIterator[PriceSnapshot]:
        symbols = {i.symbol for i in instruments if self.supports(i)}

        async def subscribe(ws: WebSocketLike) -> None:
            for symbol in sorted(symbols):
                await ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))

        def parse(raw: str | bytes) -> Iterable[PriceSnapshot]:
            return parse_trades(raw, symbols)

        return reconnecting_stream(
            name=self.name,
            url=BASE_URL + self._api_key,
            on_connect=subscribe,
            parse=parse,
            connector=self._connector,
            sleep=self._sleep,
            max_backoff=self._max_backoff,
        )
