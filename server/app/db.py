import os
import sqlite3
from contextlib import contextmanager
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
        conn.executescript(SCHEMA)


@contextmanager
def connect():
    conn = sqlite3.connect(db_path(), isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
