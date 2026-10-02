from datetime import UTC , datetime
from enum import StrEnum
from pydantic import BaseModel, Field, AwareDatetime, ConfigDict, field_validator , Field

class AssetClass(StrEnum): 
    equity : str = "equity"