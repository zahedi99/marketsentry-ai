"""Live price watcher: shows the latest stored snapshot per instrument.

Reads only from the database (latest_snapshots), so it costs 0 API requests: the
scheduler is the only thing that talks to the provider. Run with `make watch`.
"""

import argparse
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from market_core.models import PriceSnapshot

GREEN, RED, DIM, BOLD, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m"


def format_price(price: Decimal) -> str:
    """Drop storage padding (340.42001000 -> 340.42001), keeping at least 2 decimals."""
    trimmed = price.normalize()
    if -trimmed.as_tuple().exponent < 2:  # type: ignore[operator]
        trimmed = trimmed.quantize(Decimal("0.01"))
    return f"{trimmed:f}"


def format_age(age: timedelta) -> str:
    """How long ago, compactly: 45s, 12m, 3h, 2d."""
    seconds = max(0, int(age.total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def change_marker(price: Decimal, previous: Decimal | None) -> str:
    """Arrow showing the move since the watcher's previous refresh."""
    if previous is None or price == previous:
        return " "
    return f"{GREEN}^{RESET}" if price > previous else f"{RED}v{RESET}"


def render(
    snapshots: dict[str, PriceSnapshot],
    previous: dict[str, Decimal],
    now: datetime,
    tz: ZoneInfo,
) -> list[str]:
    """The screen as lines of text. Pure: no I/O, so it can be tested directly."""
    lines = [
        f"{BOLD}MarketSentry live prices{RESET}  "
        f"{DIM}{now.astimezone(tz):%Y-%m-%d %H:%M:%S} {tz.key} | from database, 0 API calls{RESET}",
        f"{DIM}{'symbol':<9}  {'price':>14}    {'quoted (local)':<19}  {'age':>4}{RESET}",
    ]
    if not snapshots:
        lines.append("no prices stored yet: run `make live`, `make stream` or `make capture`")
    for symbol in sorted(snapshots):
        snap = snapshots[symbol]
        quoted = snap.observed_at.astimezone(tz)
        marker = change_marker(snap.price, previous.get(symbol))
        age = format_age(now - snap.observed_at)
        lines.append(
            f"{symbol:<9}  {format_price(snap.price):>14} {marker}"
            f"  {quoted:%a %d %b %H:%M:%S}  {age:>4}"
        )
    lines.append(f"\n{DIM}Ctrl+C to stop{RESET}")
    return lines


def main() -> None:
    from ms_db.repositories import latest_snapshots
    from ms_db.session import new_session
    from worker.config import load_environment, optional

    parser = argparse.ArgumentParser(description="Watch the latest stored prices.")
    parser.add_argument("--every", type=float, default=2.0, help="refresh seconds (default 2)")
    args = parser.parse_args()

    load_environment()
    tz = ZoneInfo(optional("USER_TIMEZONE", "Europe/London"))
    previous: dict[str, Decimal] = {}
    try:
        while True:
            with new_session() as session:
                snapshots = latest_snapshots(session)
            lines = render(snapshots, previous, datetime.now(UTC), tz)
            print("\033[2J\033[H" + "\n".join(lines), flush=True)  # clear screen, redraw
            previous = {symbol: snap.price for symbol, snap in snapshots.items()}
            time.sleep(args.every)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
