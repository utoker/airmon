from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


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
