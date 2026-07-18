#!/usr/bin/env python3
"""Daily retention pass on the server's readings table: delete old rows, vacuum.

The UI's longest range is 7 days; 30 days is 4x headroom. Config via
AIRMON_SERVER_RETENTION_DAYS. Invoked by airmon-maintenance.timer in the
homelab repo alongside the pi-side maintenance step.
"""
import logging
import os
import sys

from . import db

log = logging.getLogger("airmon.server.maintenance")


def run() -> int:
    logging.basicConfig(
        level=os.environ.get("AIRMON_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    days = int(os.environ.get("AIRMON_SERVER_RETENTION_DAYS", "30"))

    # Make sure the schema and WAL PRAGMA are applied even if the FastAPI
    # server has never started against this db.
    db.init_db()

    size_before = db.size_bytes()
    with db.connect() as conn:
        count_before = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    log.info("server.db before: %d rows, %d bytes", count_before, size_before)

    deleted, remaining = db.prune_older_than(days)
    log.info("pruned %d rows older than %d days (%d rows remain)",
             deleted, days, remaining)

    if deleted > 0:
        db.vacuum()
        log.info("vacuumed")

    size_after = db.size_bytes()
    log.info("server.db after:  %d rows, %d bytes (reclaimed %d bytes)",
             remaining, size_after, size_before - size_after)
    return 0


if __name__ == "__main__":
    sys.exit(run())
