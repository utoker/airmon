import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "airmon.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id TEXT PRIMARY KEY,
    captured_at TEXT NOT NULL,
    pm1 REAL,
    pm25 REAL,
    pm4 REAL,
    pm10 REAL,
    co2_ppm INTEGER,
    co2_warming INTEGER NOT NULL DEFAULT 0,
    temp_c REAL,
    rh_pct REAL,
    received_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_readings_captured_at ON readings(captured_at);
"""


def db_path() -> Path:
    return Path(os.environ.get("AIRMON_DB_PATH", str(DEFAULT_DB_PATH)))


def init_db() -> None:
    with sqlite3.connect(db_path()) as conn:
        # WAL lets FastAPI's per-request INSERTs proceed concurrently with a
        # maintenance DELETE/VACUUM; busy_timeout covers VACUUM's brief
        # exclusive-lock window. Both PRAGMAs are idempotent.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
    finally:
        conn.close()


def prune_older_than(days: int) -> tuple[int, int]:
    """Delete readings whose captured_at is older than `days` days ago.

    captured_at is stored as ISO-8601 with `+00:00` tz suffix; lexicographic
    comparison is safe because every row has the same suffix. Returns
    (deleted, remaining_total).
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM readings WHERE captured_at < ?",
            (cutoff,),
        )
        deleted = cur.rowcount
        remaining = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    return deleted, remaining


def vacuum() -> None:
    with connect() as conn:
        conn.execute("VACUUM")


def size_bytes() -> int:
    return db_path().stat().st_size
