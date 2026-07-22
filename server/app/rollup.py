"""Tiered downsampling: aggregate raw readings into minute and hour buckets.

Storing raw 5s samples forever is unbounded; storing per-minute and per-hour
summaries keeps the DB near ~100 MB indefinitely. See CLAUDE.md task brief for
the design (raw 14d, minute 90d, hour forever; avg/min/max/count per sensor).

The rollup is idempotent (INSERT OR REPLACE keyed on bucket_start). It is
invoked once per day by airmon-maintenance.timer, but running it more often
is safe and cheap.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Columns that get avg/min/max/n; each raw column can independently be NULL
# (agent tolerates per-sensor read failures), so we track per-column counts.
_SENSOR_COLS = ("pm1", "pm25", "pm4", "pm10", "temp_c", "rh_pct")

# Field name aliases used in the aggregate tables (temp_c -> temp, rh_pct -> rh,
# so column prefixes are consistent and short).
_ALIAS = {"temp_c": "temp", "rh_pct": "rh"}


def _agg_col_defs() -> str:
    parts = []
    for c in _SENSOR_COLS:
        p = _ALIAS.get(c, c)
        parts.append(f"{p}_avg REAL, {p}_min REAL, {p}_max REAL, {p}_n INTEGER")
    # co2 is separate: aggregates exclude co2_warming rows.
    parts.append("co2_avg REAL, co2_min REAL, co2_max REAL, co2_n INTEGER")
    parts.append("co2_warming_n INTEGER NOT NULL DEFAULT 0")
    return ", ".join(parts)


SCHEMA = f"""
CREATE TABLE IF NOT EXISTS readings_minute (
    bucket_start TEXT PRIMARY KEY,
    n INTEGER NOT NULL,
    {_agg_col_defs()}
);
CREATE TABLE IF NOT EXISTS readings_hour (
    bucket_start TEXT PRIMARY KEY,
    n INTEGER NOT NULL,
    {_agg_col_defs()}
);
"""


def _select_columns() -> str:
    """Build the AVG/MIN/MAX/n column list for a rollup query."""
    parts = []
    for c in _SENSOR_COLS:
        p = _ALIAS.get(c, c)
        parts.append(
            f"AVG({c}) AS {p}_avg, "
            f"MIN({c}) AS {p}_min, "
            f"MAX({c}) AS {p}_max, "
            f"SUM(CASE WHEN {c} IS NOT NULL THEN 1 ELSE 0 END) AS {p}_n"
        )
    # co2 stats are computed only on non-warming rows so a 3-minute warm-up
    # spike (which reads ~400 ppm falsely) doesn't corrupt the average.
    parts.append(
        "AVG(CASE WHEN co2_warming = 0 THEN co2_ppm END) AS co2_avg, "
        "MIN(CASE WHEN co2_warming = 0 THEN co2_ppm END) AS co2_min, "
        "MAX(CASE WHEN co2_warming = 0 THEN co2_ppm END) AS co2_max, "
        "SUM(CASE WHEN co2_warming = 0 AND co2_ppm IS NOT NULL THEN 1 ELSE 0 END) AS co2_n"
    )
    parts.append("SUM(co2_warming) AS co2_warming_n")
    return ", ".join(parts)


def _insert_columns() -> list[str]:
    cols = ["bucket_start", "n"]
    for c in _SENSOR_COLS:
        p = _ALIAS.get(c, c)
        cols.extend([f"{p}_avg", f"{p}_min", f"{p}_max", f"{p}_n"])
    cols.extend(["co2_avg", "co2_min", "co2_max", "co2_n", "co2_warming_n"])
    return cols


_MINUTE_FMT = "%Y-%m-%dT%H:%M:00+00:00"
_HOUR_FMT = "%Y-%m-%dT%H:00:00+00:00"


def init_rollup_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


@dataclass
class RollupResult:
    minute_upserted: int
    hour_upserted: int
    range_start: str
    range_end_exclusive: str


def _bucket_boundary(now: datetime, resolution: str) -> str:
    """Latest bucket boundary that is fully in the past. Anything with a
    bucket_start >= this is 'still in progress' and should not be rolled up."""
    if resolution == "minute":
        b = now.replace(second=0, microsecond=0)
    elif resolution == "hour":
        b = now.replace(minute=0, second=0, microsecond=0)
    else:
        raise ValueError(resolution)
    return b.isoformat()


def _rollup_one(
    conn: sqlite3.Connection,
    target_table: str,
    bucket_fmt: str,
    range_start_iso: str,
    range_end_iso: str,
) -> int:
    """Aggregate readings in [range_start_iso, range_end_iso) into target_table
    using bucket_fmt (a strftime pattern). Returns rows upserted."""
    insert_cols = _insert_columns()
    placeholders = ", ".join(["?"] * len(insert_cols))
    col_list = ", ".join(insert_cols)

    query = f"""
        SELECT
            strftime('{bucket_fmt}', captured_at) AS bucket_start,
            COUNT(*) AS n,
            {_select_columns()}
        FROM readings
        WHERE captured_at >= ? AND captured_at < ?
        GROUP BY bucket_start
    """
    rows = conn.execute(query, (range_start_iso, range_end_iso)).fetchall()
    if not rows:
        return 0

    conn.executemany(
        f"INSERT OR REPLACE INTO {target_table} ({col_list}) VALUES ({placeholders})",
        [tuple(r) for r in rows],
    )
    return len(rows)


def rollup_recent(
    conn: sqlite3.Connection,
    now: datetime | None = None,
    lookback_days: int = 14,
) -> RollupResult:
    """Recompute minute and hour buckets in the last `lookback_days`.

    Only complete buckets are rolled up (in-progress minute/hour is skipped).
    Runs directly against raw readings, so it is only accurate for buckets
    whose raw rows are still present; call this before pruning raw rows.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    minute_end = _bucket_boundary(now, "minute")
    hour_end = _bucket_boundary(now, "hour")
    range_start = (now - timedelta(days=lookback_days)).isoformat()

    m = _rollup_one(conn, "readings_minute", _MINUTE_FMT, range_start, minute_end)
    h = _rollup_one(conn, "readings_hour", _HOUR_FMT, range_start, hour_end)
    return RollupResult(
        minute_upserted=m,
        hour_upserted=h,
        range_start=range_start,
        range_end_exclusive=hour_end,
    )


def backfill_all(conn: sqlite3.Connection, now: datetime | None = None) -> RollupResult:
    """One-time: aggregate every raw row into minute and hour tables.

    Idempotent (INSERT OR REPLACE), so safe to re-run. Excludes the currently
    in-progress minute/hour so we don't create half-buckets."""
    if now is None:
        now = datetime.now(timezone.utc)
    minute_end = _bucket_boundary(now, "minute")
    hour_end = _bucket_boundary(now, "hour")
    first = conn.execute("SELECT MIN(captured_at) FROM readings").fetchone()[0]
    if first is None:
        return RollupResult(0, 0, "", minute_end)

    m = _rollup_one(conn, "readings_minute", _MINUTE_FMT, first, minute_end)
    h = _rollup_one(conn, "readings_hour", _HOUR_FMT, first, hour_end)
    return RollupResult(
        minute_upserted=m,
        hour_upserted=h,
        range_start=first,
        range_end_exclusive=hour_end,
    )


def verify_bucket(
    conn: sqlite3.Connection,
    bucket_start: str,
    resolution: str,
) -> tuple[bool, dict]:
    """Recompute one bucket from raw and compare to the stored aggregate row.

    Returns (matches, diagnostic_dict). Used before pruning raw data to prove
    the aggregate is faithful. Compares within a small float tolerance.
    """
    if resolution == "minute":
        table, fmt = "readings_minute", _MINUTE_FMT
    elif resolution == "hour":
        table, fmt = "readings_hour", _HOUR_FMT
    else:
        raise ValueError(resolution)

    stored = conn.execute(
        f"SELECT * FROM {table} WHERE bucket_start = ?", (bucket_start,)
    ).fetchone()
    if stored is None:
        return False, {"reason": "not present in rollup table"}

    direct = conn.execute(
        f"SELECT COUNT(*) AS n, {_select_columns()} FROM readings "
        f"WHERE strftime('{fmt}', captured_at) = ?",
        (bucket_start,),
    ).fetchone()
    if direct["n"] == 0:
        return False, {"reason": "no raw rows for this bucket"}

    stored_d = dict(stored)
    direct_d = dict(direct)
    diffs = {}
    for key in stored_d:
        if key == "bucket_start":
            continue
        s, d = stored_d[key], direct_d.get(key)
        if s is None and d is None:
            continue
        if s is None or d is None:
            diffs[key] = (s, d)
            continue
        if isinstance(s, float) or isinstance(d, float):
            if abs(float(s) - float(d)) > 1e-6:
                diffs[key] = (s, d)
        elif s != d:
            diffs[key] = (s, d)
    return (len(diffs) == 0), {"diffs": diffs, "bucket": bucket_start}


def query_aggregated(
    conn: sqlite3.Connection,
    bucket_fmt: str,
    since_iso: str,
    until_iso: str,
) -> list[sqlite3.Row]:
    """Aggregate raw `readings` into buckets on the fly for [since, until).

    Same column shape as `SELECT * FROM readings_minute/hour`, so callers can
    hand rows to the same response mapper. Used at query time so the UI sees
    fresh data even before the daily maintenance rollup has run.
    """
    query = f"""
        SELECT
            strftime('{bucket_fmt}', captured_at) AS bucket_start,
            COUNT(*) AS n,
            {_select_columns()}
        FROM readings
        WHERE captured_at >= ? AND captured_at < ?
        GROUP BY bucket_start
        ORDER BY bucket_start ASC
    """
    return conn.execute(query, (since_iso, until_iso)).fetchall()


def prune_raw_older_than(
    conn: sqlite3.Connection, cutoff_iso: str
) -> int:
    cur = conn.execute("DELETE FROM readings WHERE captured_at < ?", (cutoff_iso,))
    return cur.rowcount


def prune_minute_older_than(
    conn: sqlite3.Connection, cutoff_iso: str
) -> int:
    cur = conn.execute(
        "DELETE FROM readings_minute WHERE bucket_start < ?", (cutoff_iso,)
    )
    return cur.rowcount
