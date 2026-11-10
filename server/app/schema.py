from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from .purifier import MAX_BOOST_MINUTES


class Reading(BaseModel):
    id: UUID
    captured_at: datetime
    pm1: float | None = None
    pm25: float | None = None
    pm4: float | None = None
    pm10: float | None = None
    co2_ppm: int | None = None
    co2_warming: bool = False
    temp_c: float | None = None
    rh_pct: float | None = None


class ReadingBatch(BaseModel):
    readings: list[Reading] = Field(min_length=1)


class PurifierBoost(BaseModel):
    # 0 clears the boost.
    minutes: int = Field(ge=0, le=MAX_BOOST_MINUTES)
