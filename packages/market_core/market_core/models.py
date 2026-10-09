from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


class AssetClass(StrEnum):
    EQUITY = "equity"
    INDEX = "index"
    FX = "fx"
    CRYPTO = "crypto"
    COMMODITY = "commodity"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Instrument(StrictModel):
    symbol: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    asset_class: AssetClass
    currency: str = Field(pattern=r"^[A-Z]{3}$")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("symbol cannot be empty or whitespace")
        return s


class PriceSnapshot(StrictModel):
    symbol: str = Field(min_length=1, max_length=20)
    observed_at: AwareDatetime
    price: Decimal = Field(gt=0)
    volume: int | None = Field(default=None, ge=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("symbol cannot be empty or whitespace")
        return s

    @field_validator("observed_at")
    @classmethod
    def to_utc(cls, v: datetime) -> datetime:
        return v.astimezone(UTC)


class Move(StrictModel):
    symbol: str = Field(min_length=1, max_length=20)
    start_at: AwareDatetime
    end_at: AwareDatetime
    start_price: Decimal = Field(gt=0)
    end_price: Decimal = Field(gt=0)
    change: Decimal
    change_pct: Decimal


class DailyClose(StrictModel):
    """One instrument's closing price for one trading day."""

    symbol: str
    day: date
    close: Decimal = Field(gt=0)
