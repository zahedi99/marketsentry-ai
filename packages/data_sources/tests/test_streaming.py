"""Streaming tests. No network: a fake connector plays the WebSocket server.

Binance messages are trimmed copies of real ones (2026-10-09). Finnhub messages follow
its documentation (not yet verified live: needs an API key).
"""

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from data_sources.streaming.base import StreamingProvider, WebSocketLike
from data_sources.streaming.binance import BinanceStream, binance_pair, parse_mini_ticker
from data_sources.streaming.finnhub import FinnhubStream, parse_trades
from market_core.models import AssetClass, Instrument, PriceSnapshot

BTC = Instrument(symbol="BTC/USD", name="Bitcoin", asset_class=AssetClass.CRYPTO, currency="USD")
ETH = Instrument(symbol="ETH/USD", name="Ether", asset_class=AssetClass.CRYPTO, currency="USD")
EUR = Instrument(symbol="EUR/USD", name="Euro", asset_class=AssetClass.FX, currency="USD")
AAPL = Instrument(symbol="AAPL", name="Apple", asset_class=AssetClass.EQUITY, currency="USD")
SPY = Instrument(symbol="SPY", name="S&P 500 ETF", asset_class=AssetClass.INDEX, currency="USD")


def mini_ticker(pair: str, price: str, ms: int = 1791549496016) -> str:
    stream = f"{pair.lower()}@miniTicker"
    data = {"e": "24hrMiniTicker", "E": ms, "s": pair, "c": price}
    return json.dumps({"stream": stream, "data": data})


# --- fake WebSocket server --------------------------------------------------------


class FakeWebSocket:
    def __init__(self, messages: Sequence[str]) -> None:
        self._messages = list(messages)
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def _iterate(self) -> AsyncIterator[str]:
        for message in self._messages:
            yield message

    def __aiter__(self) -> AsyncIterator[str]:
        return self._iterate()


class FakeServer:
    """Each connection attempt takes the next script: a list of messages, or an exception."""

    def __init__(self, *scripts: Sequence[str] | Exception) -> None:
        self._scripts = list(scripts)
        self.urls: list[str] = []
        self.sockets: list[FakeWebSocket] = []
        self.sleeps: list[float] = []

    @asynccontextmanager
    async def connect(self, url: str) -> AsyncIterator[WebSocketLike]:
        self.urls.append(url)
        script = self._scripts.pop(0) if self._scripts else []
        if isinstance(script, Exception):
            raise script
        ws = FakeWebSocket(script)
        self.sockets.append(ws)
        yield ws

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


async def take(stream: AsyncIterator[PriceSnapshot], n: int) -> list[PriceSnapshot]:
    out: list[PriceSnapshot] = []
    async for snapshot in stream:
        out.append(snapshot)
        if len(out) == n:
            break
    return out


# --- Binance --------------------------------------------------------------------


def test_binance_pair() -> None:
    assert binance_pair("BTC/USD") == "BTCUSDT"


def test_parse_mini_ticker() -> None:
    (snap,) = parse_mini_ticker(mini_ticker("BTCUSDT", "83162.00000000"), {"BTCUSDT": "BTC/USD"})

    assert snap.symbol == "BTC/USD"
    assert snap.price == Decimal("83162.00000000")
    assert snap.observed_at == datetime(2026, 10, 9, 12, 38, 16, 16000, tzinfo=UTC)
    assert snap.volume is None


@pytest.mark.parametrize(
    "raw",
    [
        mini_ticker("DOGEUSDT", "0.1"),  # not subscribed
        json.dumps({"stream": "x", "data": {"e": "trade", "s": "BTCUSDT"}}),  # other event
        "not json",
        json.dumps({"no": "data"}),
    ],
)
def test_parse_mini_ticker_ignores_other_messages(raw: str) -> None:
    assert parse_mini_ticker(raw, {"BTCUSDT": "BTC/USD"}) == []


def test_binance_supports_only_usd_crypto() -> None:
    stream = BinanceStream()
    assert stream.supports(BTC)
    assert not stream.supports(EUR)  # FX: Binance's EUR pairs aren't real FX rates
    assert not stream.supports(AAPL)


def test_binance_satisfies_the_contract() -> None:
    assert isinstance(BinanceStream(), StreamingProvider)


async def test_binance_streams_supported_instruments() -> None:
    server = FakeServer([mini_ticker("BTCUSDT", "83162"), mini_ticker("ETHUSDT", "2500.95")])
    stream = BinanceStream(connector=server.connect, sleep=server.sleep)

    snaps = await take(stream.stream([BTC, ETH, EUR, AAPL]), 2)

    assert [(s.symbol, s.price) for s in snaps] == [
        ("BTC/USD", Decimal("83162")),
        ("ETH/USD", Decimal("2500.95")),
    ]
    assert server.urls[0].endswith("btcusdt@miniTicker/ethusdt@miniTicker")


async def test_stream_reconnects_after_failures_with_backoff() -> None:
    server = FakeServer(OSError("down"), OSError("still down"), [mini_ticker("BTCUSDT", "1")])
    stream = BinanceStream(connector=server.connect, sleep=server.sleep)

    snaps = await take(stream.stream([BTC]), 1)

    assert snaps[0].price == Decimal("1")
    assert server.sleeps == [1.0, 2.0]  # doubled after the second failure
    assert len(server.urls) == 3


async def test_stream_reconnects_when_server_closes() -> None:
    server = FakeServer([mini_ticker("BTCUSDT", "1")], [mini_ticker("BTCUSDT", "2")])
    stream = BinanceStream(connector=server.connect, sleep=server.sleep)

    snaps = await take(stream.stream([BTC]), 2)

    assert [s.price for s in snaps] == [Decimal("1"), Decimal("2")]
    assert server.sleeps == [1.0]  # backoff reset after receiving data


async def test_backoff_is_capped() -> None:
    server = FakeServer(*[OSError()] * 6, [mini_ticker("BTCUSDT", "1")])
    stream = BinanceStream(connector=server.connect, sleep=server.sleep, max_backoff=5)

    await take(stream.stream([BTC]), 1)

    assert server.sleeps == [1, 2, 4, 5, 5, 5]


# --- Finnhub --------------------------------------------------------------------


def trades(*rows: tuple[str, float, int]) -> str:
    data = [{"s": s, "p": p, "t": t, "v": 100} for s, p, t in rows]
    return json.dumps({"type": "trade", "data": data})


def test_parse_trades_keeps_latest_per_symbol() -> None:
    raw = trades(("AAPL", 340.1, 1000), ("AAPL", 340.3, 3000), ("AAPL", 340.2, 2000))

    (snap,) = parse_trades(raw, {"AAPL"})

    assert snap.price == Decimal("340.3")
    assert snap.observed_at == datetime.fromtimestamp(3, tz=UTC)


@pytest.mark.parametrize("raw", [json.dumps({"type": "ping"}), trades(("TSLA", 1.0, 1)), "garbage"])
def test_parse_trades_ignores_other_messages(raw: str) -> None:
    assert parse_trades(raw, {"AAPL"}) == []


def test_finnhub_requires_a_key() -> None:
    with pytest.raises(ValueError):
        FinnhubStream("  ")


def test_finnhub_supports_stocks_and_index_etfs() -> None:
    stream = FinnhubStream("k")
    assert stream.supports(AAPL) and stream.supports(SPY)
    assert not stream.supports(BTC) and not stream.supports(EUR)


async def test_finnhub_subscribes_then_streams() -> None:
    server = FakeServer([trades(("AAPL", 340.42, 1000))])
    stream = FinnhubStream("secret-key", connector=server.connect, sleep=server.sleep)

    snaps = await take(stream.stream([AAPL, SPY, BTC]), 1)

    assert snaps[0].symbol == "AAPL"
    sent = [json.loads(m) for m in server.sockets[0].sent]
    assert sent == [
        {"type": "subscribe", "symbol": "AAPL"},
        {"type": "subscribe", "symbol": "SPY"},
    ]


async def test_finnhub_key_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    server = FakeServer(OSError("down"), [trades(("AAPL", 1.0, 1))])
    stream = FinnhubStream("secret-key", connector=server.connect, sleep=server.sleep)

    with caplog.at_level("DEBUG"):
        await take(stream.stream([AAPL]), 1)

    assert "secret-key" in server.urls[0]  # Finnhub needs it in the URL…
    assert "secret-key" not in caplog.text  # …but it never reaches the logs
