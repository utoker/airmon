import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from .db import connect, init_db
from .schema import ReadingBatch


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="airmon server", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/readings")
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


@app.get("/readings")
def get_readings(limit: int = 100) -> dict:
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be 1..1000")
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM readings ORDER BY captured_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {"readings": [dict(r) for r in rows]}
