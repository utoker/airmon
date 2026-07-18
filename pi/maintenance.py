#!/usr/bin/env python3
"""Daily maintenance for the Pi's buffer.db: prune sent+aged rows, then vacuum.

Never touches sent=0 rows (unsent readings are the only copy that exists).
Invoked by airmon-maintenance.timer in the homelab repo, not the agent loop.
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import buffer as buffer_mod

log = logging.getLogger("airmon.maintenance")


def run() -> int:
    logging.basicConfig(
        level=os.environ.get("AIRMON_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = config.load()
    buf = buffer_mod.Buffer(cfg.buffer_db_path)

    size_before = buf.size_bytes()
    sent_before, unsent_before = buf.sent_unsent_counts()
    log.info("buffer before: %d sent, %d unsent, %d bytes",
             sent_before, unsent_before, size_before)

    deleted, remaining = buf.prune_sent(cfg.buffer_retention_days)
    log.info("pruned %d sent rows older than %d days (%d rows remain)",
             deleted, cfg.buffer_retention_days, remaining)

    if deleted > 0:
        buf.vacuum()
        log.info("vacuumed")

    size_after = buf.size_bytes()
    sent_after, unsent_after = buf.sent_unsent_counts()
    log.info("buffer after:  %d sent, %d unsent, %d bytes (reclaimed %d bytes)",
             sent_after, unsent_after, size_after, size_before - size_after)

    if unsent_after != unsent_before:
        log.error("unsent count changed (%d -> %d); prune should never touch sent=0",
                  unsent_before, unsent_after)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
