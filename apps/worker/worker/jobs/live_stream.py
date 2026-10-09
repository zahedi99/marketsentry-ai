"""Live stream: store streamed prices so `make watch` shows them within seconds.

Runs every configured StreamingProvider at once (Binance for crypto; Finnhub for US
stocks if FINNHUB_API_KEY is set) and saves at most one snapshot per symbol every
`min_interval` seconds. Providers can push many updates per second; storing each one
would flood the database for no benefit to a briefing.

Run with `make live`.
"""

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from data_sources.streaming.base import StreamingProvider
from market_core.models import Instrument, PriceSnapshot

log = logging.getLogger(__name__)

SaveFn = Callable[[PriceSnapshot, str], bool]  # (snapshot, source) -> newly stored?


class Throttle:
    """Lets each symbol through at most once per `min_interval` seconds of *market* time.

    Uses each snapshot's own timestamp (observed_at), not the wall clock, so the result
    doesn't depend on how quickly updates happen to be processed.
    """

    def __init__(self, min_interval: float) -> None:
        self._min_interval = timedelta(seconds=min_interval)
        self._last: dict[str, datetime] = {}

    def ready(self, snapshot: PriceSnapshot) -> bool:
        last = self._last.get(snapshot.symbol)
        if last is not None and snapshot.observed_at - last < self._min_interval:
            return False
        self._last[snapshot.symbol] = snapshot.observed_at
        return True


async def stream_to_database(
    providers: Sequence[StreamingProvider],
    instruments: Sequence[Instrument],
    save: SaveFn,
    throttle: Throttle,
    *,
    stop_after: int | None = None,
) -> int:
    """Merge all provider streams and save throttled snapshots. Returns the number saved.

    Runs until cancelled (Ctrl+C), or until `stop_after` snapshots are saved (for tests).
    """
    queue: asyncio.Queue[tuple[PriceSnapshot, str]] = asyncio.Queue()

    async def pump(provider: StreamingProvider) -> None:
        async for snapshot in provider.stream(instruments):
            await queue.put((snapshot, provider.name))

    active = [p for p in providers if any(p.supports(i) for i in instruments)]
    if not active:
        log.warning("no streaming provider supports any watchlist instrument")
        return 0
    for provider in active:
        covered = [i.symbol for i in instruments if provider.supports(i)]
        log.info("%s: streaming %s", provider.name, ", ".join(covered))

    tasks = [asyncio.create_task(pump(p)) for p in active]
    saved = 0
    try:
        while stop_after is None or saved < stop_after:
            snapshot, source = await queue.get()
            if not throttle.ready(snapshot):
                continue
            if save(snapshot, source):
                saved += 1
                log.info("%s %s (%s)", snapshot.symbol, snapshot.price, source)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return saved


def main() -> None:
    from data_sources.streaming.binance import BinanceStream
    from data_sources.streaming.finnhub import FinnhubStream
    from ms_db.repositories import list_instruments, save_snapshot
    from ms_db.session import new_session
    from worker.config import load_environment, optional

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("websockets").setLevel(logging.WARNING)
    load_environment()

    with new_session() as session:
        instruments = list_instruments(session)
    if not instruments:
        raise SystemExit("The watchlist is empty: run `make seed` first.")

    providers: list[StreamingProvider] = [BinanceStream()]
    finnhub_key = optional("FINNHUB_API_KEY", "")
    if finnhub_key:
        providers.append(FinnhubStream(finnhub_key))
    else:
        log.info("FINNHUB_API_KEY not set: streaming crypto only (stocks via `make stream`)")

    def save(snapshot: PriceSnapshot, source: str) -> bool:
        with new_session() as session:
            stored = save_snapshot(session, snapshot, source=source)
            session.commit()
            return stored

    try:
        asyncio.run(stream_to_database(providers, instruments, save, Throttle(2.0)))
    except KeyboardInterrupt:
        log.info("live stream stopped")


if __name__ == "__main__":
    main()
