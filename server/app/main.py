import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .db import connect, init_db
from .schema import ReadingBatch

# Tier definitions (resolution label, seconds per bucket, source table).
# API picks the finest tier whose point count fits POINT_TARGET_MAX.
_TIER_RAW = ("5s", 5, "readings")
_TIER_MINUTE = ("1m", 60, "readings_minute")
_TIER_HOUR = ("1h", 3600, "readings_hour")
# Prefer more detail; upper bound loose so Recharts stays responsive. Bands
# roughly: 1h->raw (720), 6h->minute (360), 24h->minute (1440), 7d->hour (168).
_POINT_TARGET_MAX = 2000


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="airmon server", lifespan=lifespan)
api = APIRouter(prefix="/api")


@api.get("/health")
def health() -> dict:
    return {"status": "ok"}


@api.post("/readings")
def post_readings(batch: ReadingBatch) -> dict:
    inserted = 0
    duplicates = 0
    with connect() as conn:
        for r in batch.readings:
            try:
                conn.execute(
                    """
                    INSERT INTO readings
                        (id, captured_at, pm1, pm25, pm4, pm10,
                         co2_ppm, co2_warming, temp_c, rh_pct)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(r.id),
                        r.captured_at.isoformat(),
                        r.pm1, r.pm25, r.pm4, r.pm10,
                        r.co2_ppm, int(r.co2_warming),
                        r.temp_c, r.rh_pct,
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                duplicates += 1
    return {"inserted": inserted, "duplicates": duplicates, "total": len(batch.readings)}


def _pick_tier(range_seconds: float) -> tuple[str, int, str]:
    """Pick the finest tier whose point count fits in POINT_TARGET_MAX."""
    for label, bucket_s, table in (_TIER_RAW, _TIER_MINUTE, _TIER_HOUR):
        if range_seconds / bucket_s <= _POINT_TARGET_MAX:
            return label, bucket_s, table
    return _TIER_HOUR


def _row_to_response(row: sqlite3.Row, table: str) -> dict:
    """Normalize a raw or aggregate row into a common wire shape."""
    if table == "readings":
        return {
            "captured_at": row["captured_at"],
            "pm1": row["pm1"],
            "pm25": row["pm25"],
            "pm4": row["pm4"],
            "pm10": row["pm10"],
            "co2_ppm": row["co2_ppm"],
            "co2_warming": row["co2_warming"],
            "temp_c": row["temp_c"],
            "rh_pct": row["rh_pct"],
            "n": 1,
        }
    # Aggregate rows: use avg for the base field so existing chart code works,
    # expose min/max alongside for callers that want spike detection.
    return {
        "captured_at": row["bucket_start"],
        "pm1": row["pm1_avg"], "pm1_min": row["pm1_min"], "pm1_max": row["pm1_max"],
        "pm25": row["pm25_avg"], "pm25_min": row["pm25_min"], "pm25_max": row["pm25_max"],
        "pm4": row["pm4_avg"], "pm4_min": row["pm4_min"], "pm4_max": row["pm4_max"],
        "pm10": row["pm10_avg"], "pm10_min": row["pm10_min"], "pm10_max": row["pm10_max"],
        "co2_ppm": row["co2_avg"], "co2_min": row["co2_min"], "co2_max": row["co2_max"],
        "co2_warming": 0,
        "co2_warming_n": row["co2_warming_n"],
        "temp_c": row["temp_avg"], "temp_min": row["temp_min"], "temp_max": row["temp_max"],
        "rh_pct": row["rh_avg"], "rh_min": row["rh_min"], "rh_max": row["rh_max"],
        "n": row["n"],
    }


@api.get("/readings")
def get_readings(
    since: datetime | None = None,
    until: datetime | None = None,
    resolution: str | None = None,
) -> dict:
    """Return readings for [since, until), automatically downsampling large ranges.

    Tier is chosen so the returned series is ~200-2000 points. Callers can
    override with `resolution=5s|1m|1h`. The chosen tier is echoed in the
    response so the UI can label the chart.
    """
    now = datetime.now(timezone.utc)
    if until is None:
        until = now
    if since is None:
        # Default matches the SPA's shortest range.
        since = until.replace(microsecond=0)  # placeholder; UI always sends since

    range_seconds = max(1.0, (until - since).total_seconds())

    tiers = {"5s": _TIER_RAW, "1m": _TIER_MINUTE, "1h": _TIER_HOUR}
    if resolution is not None:
        if resolution not in tiers:
            raise HTTPException(status_code=400, detail="resolution must be 5s, 1m, or 1h")
        label, bucket_s, table = tiers[resolution]
    else:
        label, bucket_s, table = _pick_tier(range_seconds)

    time_col = "captured_at" if table == "readings" else "bucket_start"
    with connect() as conn:
        # ORDER BY ASC so the chart shows oldest -> newest without the client
        # having to reverse. No LIMIT: tier selection already bounds row count.
        rows = conn.execute(
            f"SELECT * FROM {table} "
            f"WHERE {time_col} >= ? AND {time_col} < ? "
            f"ORDER BY {time_col} ASC",
            (since.isoformat(), until.isoformat()),
        ).fetchall()
    return {
        "resolution": label,
        "bucket_seconds": bucket_s,
        "count": len(rows),
        "readings": [_row_to_response(r, table) for r in rows],
    }


app.include_router(api)


_STATIC_DIR = os.environ.get("AIRMON_STATIC_DIR")
if _STATIC_DIR and os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
