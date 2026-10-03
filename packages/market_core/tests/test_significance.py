from datetime import UTC, datetime
from decimal import Decimal

import pytest

from market_core.analytics import compute_move
from market_core.models import AssetClass, Move, PriceSnapshot
from market_core.significance import (
    FALLBACK_TYPICAL_MOVE,
    MIN_HISTORY,
    Level,
    Sensitivity,
    Significance,
    score_move,
    typical_move,
)

START = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)
END = datetime(2026, 10, 2, 6, 0, tzinfo=UTC)


def move(pct: str, symbol: str = "EURUSD") -> Move:
    """A Move from 100 to 100 + pct, so change_pct == pct exactly."""
    start = PriceSnapshot(symbol=symbol, observed_at=START, price=Decimal("100"))
    end = PriceSnapshot(symbol=symbol, observed_at=END, price=Decimal("100") + Decimal(pct))
    return compute_move(start, end)


def alternating_closes(n_changes: int, pct: str, start: str = "100") -> list[Decimal]:
    """Closes whose daily changes alternate +pct%, -pct%, +pct%, ..."""
    up = 1 + Decimal(pct) / 100
    down = 1 - Decimal(pct) / 100
    closes = [Decimal(start)]
    for i in range(n_changes):
        closes.append(closes[-1] * (up if i % 2 == 0 else down))
    return closes


# --- typical_move ---------------------------------------------------------------


def test_min_history_is_twenty_changes() -> None:
    assert MIN_HISTORY == 20


def test_typical_move_needs_enough_history() -> None:
    # 20 closes give only 19 daily changes: not enough.
    assert typical_move(alternating_closes(19, "1")) is None


def test_typical_move_with_exactly_enough_history() -> None:
    assert typical_move(alternating_closes(20, "1")) is not None


def test_typical_move_is_stdev_of_daily_pct_changes() -> None:
    # Changes are +2, -2, +2, ... (20 of them): mean 0, sample stdev = sqrt(80/19) = 2.0520
    result = typical_move(alternating_closes(20, "2"))

    assert isinstance(result, Decimal)
    assert float(result) == pytest.approx(2.051957, rel=1e-5)


def test_typical_move_uses_only_the_most_recent_changes() -> None:
    # A wild period (±10%) long ago, then a calm recent month (±2%).
    # Only the last MIN_HISTORY changes count, so the old wild period is ignored.
    wild = alternating_closes(10, "10")
    calm = alternating_closes(20, "2", start=str(wild[-1]))
    closes = wild + calm[1:]

    result = typical_move(closes)

    assert result is not None
    assert float(result) == pytest.approx(2.051957, rel=1e-5)


def test_typical_move_of_flat_history_is_zero() -> None:
    assert typical_move([Decimal("50")] * 21) == 0


# --- score_move: the core idea ----------------------------------------------------


def test_small_move_is_notable_for_a_calm_instrument() -> None:
    # 0.8% on EUR/USD, which normally moves 0.4%: 2x its normal -> NOTABLE
    result = score_move(move("0.8"), Decimal("0.4"), AssetClass.FX)

    assert isinstance(result, Significance)
    assert result.symbol == "EURUSD"
    assert result.change_pct == Decimal("0.8")
    assert result.typical_move == Decimal("0.4")
    assert result.score == Decimal("2")
    assert result.level is Level.NOTABLE
    assert result.used_fallback is False


def test_same_move_is_nothing_for_a_volatile_instrument() -> None:
    # 0.8% on Tesla, which normally moves 3.5%: a quiet day
    result = score_move(move("0.8", symbol="TSLA"), Decimal("3.5"), AssetClass.EQUITY)

    assert result.level is Level.NONE


def test_falls_use_absolute_size() -> None:
    # -3.2% when typical is 0.8%: 4x -> MAJOR
    result = score_move(move("-3.2", symbol="KO"), Decimal("0.8"), AssetClass.EQUITY)

    assert result.score == Decimal("4")
    assert result.level is Level.MAJOR


# --- score_move: thresholds and sensitivity ---------------------------------------


def test_default_sensitivity_is_normal() -> None:
    default = score_move(move("0.6"), Decimal("0.4"), AssetClass.FX)
    normal = score_move(move("0.6"), Decimal("0.4"), AssetClass.FX, Sensitivity.NORMAL)

    assert default == normal


@pytest.mark.parametrize(
    ("pct", "sensitivity", "expected"),
    [
        # typical move is 1, so score == |pct|
        ("0.99", Sensitivity.HIGH, Level.NONE),
        ("1.0", Sensitivity.HIGH, Level.NOTABLE),  # thresholds are inclusive
        ("2.0", Sensitivity.HIGH, Level.MAJOR),
        ("1.49", Sensitivity.NORMAL, Level.NONE),
        ("1.5", Sensitivity.NORMAL, Level.NOTABLE),
        ("2.99", Sensitivity.NORMAL, Level.NOTABLE),
        ("3.0", Sensitivity.NORMAL, Level.MAJOR),
        ("1.99", Sensitivity.LOW, Level.NONE),
        ("2.0", Sensitivity.LOW, Level.NOTABLE),
        ("4.0", Sensitivity.LOW, Level.MAJOR),
    ],
)
def test_levels_by_sensitivity(pct: str, sensitivity: Sensitivity, expected: Level) -> None:
    result = score_move(move(pct), Decimal("1"), AssetClass.EQUITY, sensitivity)

    assert result.level is expected


# --- score_move: not enough history -----------------------------------------------


def test_fallback_typical_moves() -> None:
    assert {
        AssetClass.EQUITY: Decimal("1.5"),
        AssetClass.INDEX: Decimal("1.0"),
        AssetClass.FX: Decimal("0.5"),
        AssetClass.CRYPTO: Decimal("4.0"),
        AssetClass.COMMODITY: Decimal("1.5"),
    } == FALLBACK_TYPICAL_MOVE


def test_uses_asset_class_fallback_without_history() -> None:
    # No history for a new FX pair: assume 0.5% typical. 0.8 / 0.5 = 1.6 -> NOTABLE
    result = score_move(move("0.8"), None, AssetClass.FX)

    assert result.used_fallback is True
    assert result.typical_move == Decimal("0.5")
    assert result.score == Decimal("1.6")
    assert result.level is Level.NOTABLE


# --- score_move: flat history (zero volatility) -----------------------------------


def test_any_move_after_flat_history_is_major() -> None:
    result = score_move(move("0.1"), Decimal("0"), AssetClass.EQUITY)

    assert result.level is Level.MAJOR
    assert result.score is None  # undefined: can't divide by zero


def test_no_move_after_flat_history_is_none() -> None:
    result = score_move(move("0"), Decimal("0"), AssetClass.EQUITY)

    assert result.level is Level.NONE
    assert result.score is None


# --- score_move: the reason is written by code, from real numbers -----------------


def test_reason_states_symbol_signed_move_and_multiple() -> None:
    result = score_move(move("-3.2", symbol="KO"), Decimal("0.8"), AssetClass.EQUITY)

    assert "KO" in result.reason
    assert "-3.20%" in result.reason
    assert "4.0x" in result.reason


def test_reason_shows_plus_sign_for_rises() -> None:
    result = score_move(move("0.8"), Decimal("0.4"), AssetClass.FX)

    assert "+0.80%" in result.reason


def test_reason_mentions_fallback() -> None:
    result = score_move(move("0.8"), None, AssetClass.FX)

    assert "limited history" in result.reason


def test_reason_mentions_flat_history() -> None:
    result = score_move(move("0.1"), Decimal("0"), AssetClass.EQUITY)

    assert "flat" in result.reason


def test_significance_is_frozen() -> None:
    result = score_move(move("0.8"), Decimal("0.4"), AssetClass.FX)

    with pytest.raises(ValueError):
        result.level = Level.MAJOR  # type: ignore[misc]
