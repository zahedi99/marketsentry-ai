import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from market_core.models import PriceSnapshot
from worker.watch import format_age, format_price, render

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
LONDON = ZoneInfo("Europe/London")


def plain(lines: list[str]) -> str:
    """Strip colour codes so assertions read naturally."""
    return re.sub(r"\033\[[0-9;]*m", "", "\n".join(lines))


@pytest.mark.parametrize(
    ("price", "shown"),
    [
        ("340.42001000", "340.42001"),
        ("83019.33000000", "83019.33"),
        ("773.90000000", "773.90"),
        ("1.12128000", "1.12128"),
        ("82567", "82567.00"),
    ],
)
def test_format_price(price: str, shown: str) -> None:
    assert format_price(Decimal(price)) == shown


@pytest.mark.parametrize(
    ("seconds", "shown"),
    [(5, "5s"), (59, "59s"), (60, "1m"), (3599, "59m"), (3600, "1h"), (90000, "1d"), (-3, "0s")],
)
def test_format_age(seconds: int, shown: str) -> None:
    assert format_age(timedelta(seconds=seconds)) == shown


def snap(symbol: str, price: str, minutes_ago: int) -> PriceSnapshot:
    return PriceSnapshot(
        symbol=symbol, observed_at=NOW - timedelta(minutes=minutes_ago), price=Decimal(price)
    )


def test_render_lists_symbols_sorted_with_local_time_and_age() -> None:
    snapshots = {"MSFT": snap("MSFT", "522.61", 30), "AAPL": snap("AAPL", "340.42", 5)}

    text = plain(render(snapshots, {}, NOW, LONDON))

    assert text.index("AAPL") < text.index("MSFT")
    assert "340.42" in text and "522.61" in text
    assert "12:55" in text  # 11:55 UTC shown in London time (BST)
    assert "5m" in text and "30m" in text
    assert "0 API calls" in text


def test_render_marks_moves_since_last_refresh() -> None:
    snapshots = {"AAPL": snap("AAPL", "341", 1), "MSFT": snap("MSFT", "520", 1)}
    previous = {"AAPL": Decimal("340"), "MSFT": Decimal("522")}

    lines = render(snapshots, previous, NOW, LONDON)

    aapl = next(line for line in lines if "AAPL" in line)
    msft = next(line for line in lines if "MSFT" in line)
    assert "^" in aapl  # up
    assert "v" in plain([msft]).split("520.00")[1]  # down marker after the price


def test_render_empty_database_explains_what_to_do() -> None:
    assert "make stream" in plain(render({}, {}, NOW, LONDON))
