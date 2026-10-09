"""Live price streaming over WebSockets: the contract and the shared reconnect loop.

A StreamingProvider pushes prices as they happen, unlike a MarketDataProvider, which is
asked for them. Connections drop (network blips, server restarts), so every stream
reconnects with exponential backoff and never gives up on its own.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from market_core.models import Instrument, PriceSnapshot

log = logging.getLogger(__name__)


class WebSocketLike(Protocol):
    """The part of a WebSocket connection the streams use (lets tests pass fakes)."""

    async def send(self, message: str) -> None: ...

    def __aiter__(self) -> AsyncIterator[str | bytes]: ...


Connector = Callable[[str], AbstractAsyncContextManager[WebSocketLike]]
Sleep = Callable[[float], Awaitable[None]]


def default_connector(url: str) -> AbstractAsyncContextManager[WebSocketLike]:
    return connect(url, open_timeout=10, ping_interval=20)


@runtime_checkable
class StreamingProvider(Protocol):
    name: str

    def supports(self, instrument: Instrument) -> bool:
        """Can this provider stream this instrument?"""
        ...

    def stream(self, instruments: Sequence[Instrument]) -> AsyncIterator[PriceSnapshot]:
        """Live snapshots for the supported instruments, forever (reconnecting as needed)."""
        ...


async def reconnecting_stream(
    *,
    name: str,
    url: str,
    on_connect: Callable[[WebSocketLike], Awaitable[None]],
    parse: Callable[[str | bytes], Iterable[PriceSnapshot]],
    connector: Connector = default_connector,
    sleep: Sleep = asyncio.sleep,
    max_backoff: float = 30.0,
) -> AsyncIterator[PriceSnapshot]:
    """Connect, subscribe, yield parsed snapshots; on any drop, wait and reconnect.

    Backoff doubles after each failure (1s, 2s, 4s… up to max_backoff) and resets once a
    connection delivers data. `url` may contain a credential, so it is never logged.
    """
    backoff = 1.0
    while True:
        try:
            async with connector(url) as ws:
                await on_connect(ws)
                log.info("%s: connected", name)
                async for raw in ws:
                    backoff = 1.0
                    for snapshot in parse(raw):
                        yield snapshot
            log.warning("%s: stream closed by server", name)
        except (OSError, TimeoutError, WebSocketException) as exc:
            log.warning("%s: connection problem (%s)", name, type(exc).__name__)
        log.info("%s: reconnecting in %.0fs", name, backoff)
        await sleep(backoff)
        backoff = min(backoff * 2, max_backoff)
