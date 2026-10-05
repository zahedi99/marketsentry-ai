"""How unusual is an overnight move for this instrument? (see ADR-003)

Code scores every move; agents later decide which ones become stories.
"""

import statistics
from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from itertools import pairwise

from market_core.analytics import pct_change
from market_core.models import AssetClass, Move, StrictModel

MIN_HISTORY = 20  # daily changes: both the minimum and the window

# Assumed typical daily move (%) when an instrument has too little history.
FALLBACK_TYPICAL_MOVE = {
    AssetClass.EQUITY: Decimal("1.5"),
    AssetClass.INDEX: Decimal("1.0"),
    AssetClass.FX: Decimal("0.5"),
    AssetClass.CRYPTO: Decimal("4.0"),
    AssetClass.COMMODITY: Decimal("1.5"),
}


class Level(StrEnum):
    NONE = "none"
    NOTABLE = "notable"
    MAJOR = "major"


class Sensitivity(StrEnum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


# sensitivity -> (score needed for NOTABLE, score needed for MAJOR); inclusive
THRESHOLDS = {
    Sensitivity.HIGH: (Decimal("1.0"), Decimal("2.0")),
    Sensitivity.NORMAL: (Decimal("1.5"), Decimal("3.0")),
    Sensitivity.LOW: (Decimal("2.0"), Decimal("4.0")),
}


class Significance(StrictModel):
    symbol: str
    change_pct: Decimal
    typical_move: Decimal
    score: Decimal | None  # None when the typical move is 0 (flat history)
    level: Level
    reason: str
    used_fallback: bool


def typical_move(closes: Sequence[Decimal]) -> Decimal | None:
    """Typical daily % move: sample stdev of the last MIN_HISTORY daily % changes.

    Returns None if there are fewer than MIN_HISTORY changes.
    """
    changes = [pct_change(prev, curr) for prev, curr in pairwise(closes)]
    if len(changes) < MIN_HISTORY:
        return None
    return statistics.stdev(changes[-MIN_HISTORY:])


def score_move(
    move: Move,
    typical: Decimal | None,
    asset_class: AssetClass,
    sensitivity: Sensitivity = Sensitivity.NORMAL,
) -> Significance:
    """Score a move relative to the instrument's typical move.

    `typical` comes from typical_move(); None means not enough history, so the
    asset-class fallback is used instead.
    """
    used_fallback = typical is None
    if typical is None:
        typical = FALLBACK_TYPICAL_MOVE[asset_class]

    headline = f"{move.symbol} {move.change_pct:+.2f}% overnight"

    # Flat history: any move at all is unusual, but a score is undefined (division by 0).
    if typical == 0:
        return Significance(
            symbol=move.symbol,
            change_pct=move.change_pct,
            typical_move=typical,
            score=None,
            level=Level.MAJOR if move.change_pct != 0 else Level.NONE,
            reason=f"{headline}; its recent price history is flat",
            used_fallback=used_fallback,
        )

    score = abs(move.change_pct) / typical
    notable_at, major_at = THRESHOLDS[sensitivity]

    if score >= major_at:
        level = Level.MAJOR
    elif score >= notable_at:
        level = Level.NOTABLE
    else:
        level = Level.NONE

    reason = f"{headline}, {score:.1f}x its typical daily move of {typical:.2f}%"
    if used_fallback:
        reason += " (typical move assumed for this asset class: limited history)"

    return Significance(
        symbol=move.symbol,
        change_pct=move.change_pct,
        typical_move=typical,
        score=score,
        level=level,
        reason=reason,
        used_fallback=used_fallback,
    )
