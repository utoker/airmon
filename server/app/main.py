import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .db import connect, init_db
from .schema import ReadingBatch


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


@api.get("/readings")
def get_readings(
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 1000,
) -> dict:
    if limit < 1 or limit > 10000:
        raise HTTPException(status_code=400, detail="limit must be 1..10000")
    where: list[str] = []
    params: list = []
    if since is not None:
        where.append("captured_at >= ?")
        params.append(since.isoformat())
    if until is not None:
        where.append("captured_at <= ?")
        params.append(until.isoformat())
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM readings {where_sql} ORDER BY captured_at DESC LIMIT ?",
            params,
        ).fetchall()
    return {"readings": [dict(r) for r in rows]}


app.include_router(api)


_STATIC_DIR = os.environ.get("AIRMON_STATIC_DIR")
if _STATIC_DIR and os.path.isdir(_STATIC_DIR):
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
