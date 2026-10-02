from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from market_core.analytics import compute_move, pct_change
from market_core.models import Move, PriceSnapshot

START = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)  # US close
END = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)  # before the user wakes


def snap(price: str, at: datetime = START, **overrides: Any) -> PriceSnapshot:
    fields: dict[str, Any] = {"symbol": "AAPL", "observed_at": at, "price": Decimal(price)}
    return PriceSnapshot(**(fields | overrides))


# --- pct_change ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("100", "110", "10"),  # up
        ("100", "90", "-10"),  # down
        ("200", "200", "0"),  # flat
        ("8", "10", "25"),
        ("187.50", "191.25", "2"),  # cents, still exact
    ],
)
def test_pct_change(start: str, end: str, expected: str) -> None:
    assert pct_change(Decimal(start), Decimal(end)) == Decimal(expected)


def test_pct_change_returns_decimal() -> None:
    assert isinstance(pct_change(Decimal("100"), Decimal("110")), Decimal)


@pytest.mark.parametrize("start", ["0", "-5"])
def test_pct_change_rejects_non_positive_start(start: str) -> None:
    with pytest.raises(ValueError):
        pct_change(Decimal(start), Decimal("10"))


# --- compute_move -------------------------------------------------------------


def test_compute_move() -> None:
    move = compute_move(snap("100", at=START), snap("97.5", at=END))

    assert isinstance(move, Move)
    assert move.symbol == "AAPL"
    assert move.start_at == START
    assert move.end_at == END
    assert move.start_price == Decimal("100")
    assert move.end_price == Decimal("97.5")
    assert move.change == Decimal("-2.5")
    assert move.change_pct == Decimal("-2.5")


def test_compute_move_rejects_different_symbols() -> None:
    with pytest.raises(ValueError):
        compute_move(snap("100", at=START), snap("101", at=END, symbol="MSFT"))


def test_compute_move_rejects_end_before_start() -> None:
    with pytest.raises(ValueError):
        compute_move(snap("100", at=END), snap("101", at=START))


def test_compute_move_rejects_same_timestamp() -> None:
    with pytest.raises(ValueError):
        compute_move(snap("100", at=START), snap("101", at=START))


def test_move_is_frozen() -> None:
    move = compute_move(snap("100", at=START), snap("101", at=START + timedelta(hours=1)))

    with pytest.raises(ValueError):  # pydantic's ValidationError is a ValueError
        move.change = Decimal("0")  # type: ignore[misc]
