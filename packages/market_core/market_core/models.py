from datetime import UTC , datetime
from enum import StrEnum
from decimal import Decimal
from pydantic import BaseModel, AwareDatetime, ConfigDict, field_validator , Field

class AssetClass(StrEnum): 
    EQUITY = "equity"
    INDEX = "index"
    FX = "fx"
    CRYPTO = "crypto"
    COMMODITY = "commodity"
class StrictModel(BaseModel):
    model_config = ConfigDict(extra= "forbid", frozen =True)
class Instrument(StrictModel):
    symbol: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1, max_length=100)
    asset_class: AssetClass
    currency: str = Field(pattern= r"^[A-Z]{3}$")
    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        s = v.strip().upper()
        if not s:
            raise ValueError("symbol cannot be empty or whitespace")
        return s
class PriceSnapshot(StrictModel): 
    symbol: str = Field(min_length=1, max_length=20)
    to_utc: AwareDatetime
    @field_validator("to_utc")
    @classmethod
    def to_utc(cls, v: datetime) -> datetime:
        return v.astimezone(UTC)
    price: Decimal = Field(gt=0)
    volume: int | None = Field(default=None, ge=0)
    