import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id           TEXT PRIMARY KEY,
    captured_at  TEXT NOT NULL,
    pm1          REAL,
    pm25         REAL,
    pm4          REAL,
    pm10         REAL,
    co2_ppm      INTEGER,
    co2_warming  INTEGER NOT NULL DEFAULT 0,
    temp_c       REAL,
    rh_pct       REAL,
    sent         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_readings_unsent
    ON readings(id) WHERE sent = 0;
CREATE INDEX IF NOT EXISTS idx_readings_sent_captured
    ON readings(sent, captured_at);
"""

_INSERT = """
INSERT INTO readings
    (id, captured_at, pm1, pm25, pm4, pm10,
     co2_ppm, co2_warming, temp_c, rh_pct)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_UNSENT = """
SELECT id, captured_at, pm1, pm25, pm4, pm10,
       co2_ppm, co2_warming, temp_c, rh_pct
FROM readings
WHERE sent = 0
ORDER BY captured_at ASC
LIMIT ?
"""


class Buffer:
    def __init__(self, path: str):
        self._path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            # WAL lets the agent's 1-per-5s INSERT proceed while a maintenance
            # DELETE/VACUUM holds a lock; busy_timeout covers the brief window
            # where VACUUM does need exclusive access. Both PRAGMAs are safe
            # to re-issue on every start.
            c.execute("PRAGMA journal_mode = WAL")
            c.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
        finally:
            conn.close()

    def append(self, r: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                _INSERT,
                (
                    r["id"], r["captured_at"],
                    r.get("pm1"), r.get("pm25"), r.get("pm4"), r.get("pm10"),
                    r.get("co2_ppm"), int(bool(r.get("co2_warming", False))),
                    r.get("temp_c"), r.get("rh_pct"),
                ),
            )

    def unsent(self, limit: int) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute(_SELECT_UNSENT, (limit,)).fetchall()
        return [_row_to_reading(r) for r in rows]

    def mark_sent(self, ids: list[str]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._conn() as c:
            c.execute(
                f"UPDATE readings SET sent = 1 WHERE id IN ({placeholders})",
                ids,
            )

    def pending_count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM readings WHERE sent = 0").fetchone()[0]

    def prune_sent(self, older_than_days: int) -> tuple[int, int]:
        """Delete rows where sent=1 AND captured_at older than the cutoff.

        Never touches sent=0 rows: the invariant is never drop a reading.
        The grace period lets us replay if server.db is lost or corrupted.
        Returns (deleted, remaining_total).
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)) \
            .isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self._conn() as c:
            cur = c.execute(
                "DELETE FROM readings WHERE sent = 1 AND captured_at < ?",
                (cutoff,),
            )
            deleted = cur.rowcount
            remaining = c.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        return deleted, remaining

    def vacuum(self) -> None:
        # Plain VACUUM chosen over auto_vacuum=INCREMENTAL because the db is
        # small (tens of MB) and this runs from a daily timer, not per-write.
        # Needs a brief exclusive lock; the agent's INSERTs will wait up to
        # busy_timeout for it to clear.
        with self._conn() as c:
            c.execute("VACUUM")

    def size_bytes(self) -> int:
        return Path(self._path).stat().st_size

    def sent_unsent_counts(self) -> tuple[int, int]:
        with self._conn() as c:
            row = c.execute(
                "SELECT SUM(CASE WHEN sent=1 THEN 1 ELSE 0 END), "
                "       SUM(CASE WHEN sent=0 THEN 1 ELSE 0 END) FROM readings"
            ).fetchone()
        return (row[0] or 0, row[1] or 0)


def _row_to_reading(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id":          r["id"],
        "captured_at": r["captured_at"],
        "pm1":         r["pm1"],
        "pm25":        r["pm25"],
        "pm4":         r["pm4"],
        "pm10":        r["pm10"],
        "co2_ppm":     r["co2_ppm"],
        "co2_warming": bool(r["co2_warming"]),
        "temp_c":      r["temp_c"],
        "rh_pct":      r["rh_pct"],
    }
