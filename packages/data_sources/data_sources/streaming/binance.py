"""Binance public market streams: live crypto prices, free, no account or API key.

Uses the `<pair>@miniTicker` stream, which pushes each pair's latest price about once per
second (verified live, 2026-10-09). Binance quotes crypto against USDT, a stablecoin
pegged to the US dollar, so our "BTC/USD" maps to Binance's BTCUSDT. USDT can deviate
slightly from $1; snapshots are stored with source "binance" so that's traceable.
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

BASE_URL = "wss://stream.binance.com:9443/stream?streams="


def binance_pair(symbol: str) -> str:
    """'BTC/USD' -> 'BTCUSDT'."""
    base, _, _quote = symbol.partition("/")
    return f"{base}USDT"


def parse_mini_ticker(raw: str | bytes, pairs: dict[str, str]) -> list[PriceSnapshot]:
    """One combined-stream message -> a snapshot, or nothing if it isn't one of ours."""
    try:
        data = json.loads(raw)["data"]
        if data.get("e") != "24hrMiniTicker" or data["s"] not in pairs:
            return []
        return [
            PriceSnapshot(
                symbol=pairs[data["s"]],
                observed_at=datetime.fromtimestamp(int(data["E"]) / 1000, tz=UTC),
                price=Decimal(data["c"]),
            )
        ]
    except (ValueError, KeyError, TypeError):
        return []  # malformed or unexpected message: skip it, keep streaming


class BinanceStream:
    name = "binance"

    def __init__(
        self,
        *,
        connector: Connector = default_connector,
        sleep: Sleep = asyncio.sleep,
        max_backoff: float = 30.0,
    ) -> None:
        self._connector = connector
        self._sleep = sleep
        self._max_backoff = max_backoff

    def supports(self, instrument: Instrument) -> bool:
        return instrument.asset_class is AssetClass.CRYPTO and instrument.symbol.endswith("/USD")

    def stream(self, instruments: Sequence[Instrument]) -> AsyncIterator[PriceSnapshot]:
        pairs = {binance_pair(i.symbol): i.symbol for i in instruments if self.supports(i)}
        streams = "/".join(f"{pair.lower()}@miniTicker" for pair in sorted(pairs))

        async def nothing_to_send(ws: WebSocketLike) -> None:
            return None  # subscriptions are encoded in the URL

        def parse(raw: str | bytes) -> Iterable[PriceSnapshot]:
            return parse_mini_ticker(raw, pairs)

        return reconnecting_stream(
            name=self.name,
            url=BASE_URL + streams,
            on_connect=nothing_to_send,
            parse=parse,
            connector=self._connector,
            sleep=self._sleep,
            max_backoff=self._max_backoff,
        )
