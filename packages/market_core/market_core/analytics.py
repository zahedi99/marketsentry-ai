from decimal import Decimal
from market_core.models import Move, PriceSnapshot
def pct_change(start: Decimal, end: Decimal) -> Decimal: 
    if start <=0: 
        raise ValueError("start and end prices must be non-negative")
    
    return (end - start) / start * 100
def compute_move(start: PriceSnapshot, end: PriceSnapshot) -> Move:
    raise NotImplementedError