import statistics
from collections.abc import Sequence
from decimal import Decimal 
from enum import StrEnum 
from market_core.analytics import pct_change
from market_core.models import Assetclass, Move, StrictModel
MIN_HISTORY=20 
