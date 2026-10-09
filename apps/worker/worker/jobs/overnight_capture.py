"""Overnight capture: fetch the latest price for every watchlist instrument and store it.

Built to run unattended:
- rate-limited, to stay inside the provider's free tier;
- fault-tolerant: one failing symbol is recorded and skipped, the rest carry on;
- idempotent: re-running stores nothing twice (save_snapshot uses ON CONFLICT);
- each snapshot is committed as soon as it's saved, so a crash halfway keeps the
  snapshots already captured (they're independent facts, not one all-or-nothing unit).

Run once with `make capture`.
"""

import logging
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from data_sources.market_data.base import MarketDataProvider, ProviderError, RateLimitError
from ms_db.repositories import list_instruments, save_snapshot

log = logging.getLogger(__name__)

# Twelve Data free tier: 8 requests per minute.
FREE_TIER_CALLS = 8
FREE_TIER_PERIOD_SECONDS = 60.0


class RateLimiter:
    """Allows at most `max_calls` within any `period` seconds (a sliding window).

    `clock` and `sleep` are injectable so tests can run instantly with a fake clock.
    """

    def __init__(
        self,
        max_calls: int,
        period: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_calls < 1 or period <= 0:
            raise ValueError("max_calls must be >= 1 and period must be > 0")
        self._max_calls = max_calls
        self._period = period
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()

    def wait(self) -> None:
        """Block until one more call is allowed, then record it."""
        now = self._clock()
        while self._calls and now - self._calls[0] >= self._period:
            self._calls.popleft()  # forget calls that left the window
        if len(self._calls) >= self._max_calls:
            pause = self._calls[0] + self._period - now
            log.info("rate limit: waiting %.1fs", pause)
            self._sleep(pause)
            self._calls.popleft()
            now = self._clock()
        self._calls.append(now)


@dataclass
class CaptureReport:
    """What one capture run did, per symbol."""

    saved: list[str] = field(default_factory=list)
    already_stored: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # symbol -> reason

    def summary(self) -> str:
        return (
            f"saved {len(self.saved)}, already stored {len(self.already_stored)}, "
            f"failed {len(self.failed)}"
        )


def capture_snapshots(
    session: Session,
    provider: MarketDataProvider,
    *,
    source: str,
    limiter: RateLimiter | None = None,
) -> CaptureReport:
    """Fetch and store the latest snapshot for every instrument on the watchlist."""
    report = CaptureReport()
    for instrument in list_instruments(session):
        symbol = instrument.symbol
        if limiter is not None:
            limiter.wait()
        try:
            snapshot = provider.latest_snapshot(symbol)
        except RateLimitError:
            report.failed[symbol] = "rate limited by provider"
            log.warning("%s: rate limited by provider", symbol)
            continue
        except ProviderError as exc:
            report.failed[symbol] = str(exc)
            log.warning("%s: %s", symbol, exc)
            continue

        if save_snapshot(session, snapshot, source=source):
            report.saved.append(symbol)
            log.info("%s: saved %s at %s", symbol, snapshot.price, snapshot.observed_at)
        else:
            report.already_stored.append(symbol)
            log.info("%s: already stored (%s)", symbol, snapshot.observed_at)
        session.commit()

    log.info("capture finished: %s", report.summary())
    return report


def main() -> None:
    """Run one capture against Twelve Data and the configured database."""
    from data_sources.market_data.twelve_data import TwelveDataProvider
    from ms_db.session import new_session
    from worker.config import load_environment, required

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_environment()
    provider = TwelveDataProvider(required("TWELVE_DATA_API_KEY"))
    limiter = RateLimiter(FREE_TIER_CALLS, FREE_TIER_PERIOD_SECONDS)
    try:
        with new_session() as session:
            report = capture_snapshots(session, provider, source="twelve_data", limiter=limiter)
    finally:
        provider.close()
    for symbol, reason in report.failed.items():
        print(f"FAILED {symbol}: {reason}")
    print(f"Capture done: {report.summary()}")


if __name__ == "__main__":
    main()
