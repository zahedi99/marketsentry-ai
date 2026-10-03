from decimal import Decimal

from market_core.models import Move, PriceSnapshot


def pct_change(start: Decimal, end: Decimal) -> Decimal:
    """Percentage change from start to end, e.g. 100 -> 110 gives 10."""
    if start <= 0:
        raise ValueError("start price must be positive")

    return (end - start) / start * 100


def compute_move(start: PriceSnapshot, end: PriceSnapshot) -> Move:
    """The price move of one instrument between two snapshots."""
    if start.symbol != end.symbol:
        raise ValueError(f"snapshots are for different symbols: {start.symbol} vs {end.symbol}")
    if end.observed_at <= start.observed_at:
        raise ValueError("end snapshot must be after start snapshot")

    return Move(
        symbol=start.symbol,
        start_at=start.observed_at,
        end_at=end.observed_at,
        start_price=start.price,
        end_price=end.price,
        change=end.price - start.price,
        change_pct=pct_change(start.price, end.price),
    )
