#!/usr/bin/env python3
"""Daily maintenance on the server's readings DB.

Order of operations matters here. Roll up first (needs raw rows), verify a
sample of rolled-up buckets against direct raw queries, THEN prune raw rows
that are older than the raw-tier retention, THEN prune minute rows that are
older than the minute-tier retention. Rollup and pruning happen in separate
transactions, so a partial run never destroys data we haven't rolled up yet.

Config (all optional, sensible defaults for a Raspberry Pi):
    AIRMON_TIER_RAW_DAYS         raw 5s rows kept, default 14
    AIRMON_TIER_MINUTE_DAYS      per-minute rows kept, default 90
    (hour rows are kept forever)
    AIRMON_LOG_LEVEL             default INFO

Invoked by airmon-maintenance.timer in the homelab repo, alongside the pi-side
buffer maintenance step.
"""
import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone

from . import db, rollup

log = logging.getLogger("airmon.server.maintenance")


def _sample_verify(conn, n_samples: int = 20) -> tuple[int, int]:
    """Recompute a random sample of stored aggregate rows from raw and compare.

    Returns (ok_count, checked_count). Skips silently if no aggregate rows exist
    yet (first run before backfill produced anything)."""
    ok = 0
    checked = 0
    for table, resolution in (("readings_minute", "minute"), ("readings_hour", "hour")):
        rows = conn.execute(
            f"SELECT bucket_start FROM {table} "
            f"WHERE bucket_start >= (SELECT MIN(captured_at) FROM readings) "
            f"ORDER BY random() LIMIT ?",
            (n_samples,),
        ).fetchall()
        for r in rows:
            match, info = rollup.verify_bucket(conn, r["bucket_start"], resolution)
            checked += 1
            if match:
                ok += 1
            else:
                log.error("verify failed for %s %s: %s", resolution, r["bucket_start"], info)
    return ok, checked


def run() -> int:
    logging.basicConfig(
        level=os.environ.get("AIRMON_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    raw_days = int(os.environ.get("AIRMON_TIER_RAW_DAYS", "14"))
    minute_days = int(os.environ.get("AIRMON_TIER_MINUTE_DAYS", "90"))

    db.init_db()

    size_before = db.size_bytes()
    with db.connect() as conn:
        raw_before = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        min_before = conn.execute("SELECT COUNT(*) FROM readings_minute").fetchone()[0]
        hr_before = conn.execute("SELECT COUNT(*) FROM readings_hour").fetchone()[0]
    log.info("before: raw=%d minute=%d hour=%d bytes=%d",
             raw_before, min_before, hr_before, size_before)

    # 1. Rollup. backfill_all is idempotent (INSERT OR REPLACE) and only touches
    #    buckets whose raw rows are still present, which is exactly the set that
    #    might have changed since yesterday. Cost is dominated by raw row count,
    #    which the tier keeps bounded.
    with db.connect() as conn:
        result = rollup.backfill_all(conn)
    log.info("rollup: %d minute upserts, %d hour upserts (range %s .. %s)",
             result.minute_upserted, result.hour_upserted,
             result.range_start, result.range_end_exclusive)

    # 2. Verify. Pull a random sample of aggregate rows and confirm they match a
    #    fresh direct query on raw. If any diverge, refuse to prune this run.
    with db.connect() as conn:
        ok, checked = _sample_verify(conn, n_samples=20)
    log.info("verify: %d/%d sampled aggregate rows match raw", ok, checked)
    if checked > 0 and ok != checked:
        log.error("aggregate/raw mismatch detected; refusing to prune this run")
        return 1

    # 3. Prune. Raw rows first (protected by rollup+verify above), then minute
    #    rows (whose data is preserved in hour rows). Hour rows are never pruned.
    now = datetime.now(timezone.utc)
    raw_cutoff = (now - timedelta(days=raw_days)).isoformat()
    minute_cutoff = (now - timedelta(days=minute_days)).isoformat()
    with db.connect() as conn:
        raw_deleted = rollup.prune_raw_older_than(conn, raw_cutoff)
        min_deleted = rollup.prune_minute_older_than(conn, minute_cutoff)
    log.info("pruned: raw=%d (cutoff %s), minute=%d (cutoff %s)",
             raw_deleted, raw_cutoff, min_deleted, minute_cutoff)

    # 4. Vacuum. DELETE alone leaves the file the same size, so the size win is
    #    invisible until this reclaims the freelist pages.
    if raw_deleted > 0 or min_deleted > 0:
        db.vacuum()
        log.info("vacuumed")

    size_after = db.size_bytes()
    with db.connect() as conn:
        raw_after = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        min_after = conn.execute("SELECT COUNT(*) FROM readings_minute").fetchone()[0]
        hr_after = conn.execute("SELECT COUNT(*) FROM readings_hour").fetchone()[0]
    log.info("after:  raw=%d minute=%d hour=%d bytes=%d (reclaimed %d bytes)",
             raw_after, min_after, hr_after, size_after,
             size_before - size_after)
    return 0


if __name__ == "__main__":
    sys.exit(run())
