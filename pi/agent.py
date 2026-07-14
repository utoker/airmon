#!/usr/bin/env python3
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
import buffer as buffer_mod
from drivers import gy21, mhz19b, sps30

log = logging.getLogger("airmon.agent")


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sample_all(cfg: config.Config, sps: sps30.SPS30, agent_started_monotonic: float) -> dict:
    reading: dict = {
        "id": str(uuid4()),
        "captured_at": _now_iso_utc(),
        "co2_warming": (time.monotonic() - agent_started_monotonic) < cfg.mhz19b_warmup_s,
    }

    try:
        reading["temp_c"] = gy21.read_temperature_c(cfg.i2c_bus)
        reading["rh_pct"] = gy21.read_humidity_pct(cfg.i2c_bus)
    except Exception as e:
        log.warning("gy21 read failed: %s: %s", type(e).__name__, e)

    try:
        reading["co2_ppm"] = mhz19b.read_co2_ppm(cfg.mhz19b_device)
    except Exception as e:
        log.warning("mhz19b read failed: %s: %s", type(e).__name__, e)

    try:
        pm = sps.read()
        reading["pm1"]  = pm["pm1_0_ug_m3"]
        reading["pm25"] = pm["pm2_5_ug_m3"]
        reading["pm4"]  = pm["pm4_0_ug_m3"]
        reading["pm10"] = pm["pm10_ug_m3"]
    except Exception as e:
        log.warning("sps30 read failed: %s: %s", type(e).__name__, e)

    return reading


def post_batch(cfg: config.Config, readings: list[dict]) -> None:
    body = json.dumps({"readings": readings}, default=str).encode()
    req = urllib.request.Request(
        cfg.server_url.rstrip("/") + "/readings",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=cfg.post_timeout_s) as resp:
        if resp.status // 100 != 2:
            raise RuntimeError(f"HTTP {resp.status}")
        resp.read()


def flush_all(cfg: config.Config, buf: buffer_mod.Buffer) -> int:
    total = 0
    while True:
        batch = buf.unsent(cfg.post_batch_size)
        if not batch:
            return total
        post_batch(cfg, batch)
        buf.mark_sent([r["id"] for r in batch])
        total += len(batch)


def run() -> int:
    logging.basicConfig(
        level=os.environ.get("AIRMON_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    cfg = config.load()
    log.info("starting agent: server=%s interval=%.1fs buffer=%s",
             cfg.server_url, cfg.sample_interval_s, cfg.buffer_db_path)

    buf = buffer_mod.Buffer(cfg.buffer_db_path)
    log.info("buffer: %d unsent rows at startup", buf.pending_count())

    agent_started = time.monotonic()
    backoff = 0.0
    retry_not_before = 0.0

    with sps30.SPS30(cfg.sps30_device) as sps:
        # If a previous agent was killed mid-loop the sensor is still in
        # Measuring; Start would return state 0x43. Stopping first is idempotent.
        try:
            sps.stop()
        except Exception:
            pass
        try:
            sps.start()
        except Exception as e:
            log.error("failed to start SPS30 measurement: %s", e)
            return 1
        # SPS30 needs ~1s after Start before the first sample is ready; without
        # this the first read returns 0 bytes and PM fields are null.
        time.sleep(2.0)

        try:
            while True:
                cycle_start = time.monotonic()

                reading = sample_all(cfg, sps, agent_started)
                buf.append(reading)
                log.info("sampled: pm25=%s co2=%s temp=%s rh=%s warming=%s",
                         reading.get("pm25"), reading.get("co2_ppm"),
                         reading.get("temp_c"), reading.get("rh_pct"),
                         reading["co2_warming"])

                if time.monotonic() >= retry_not_before:
                    try:
                        sent = flush_all(cfg, buf)
                        if sent:
                            log.info("flushed %d readings; %d still pending",
                                     sent, buf.pending_count())
                        backoff = 0.0
                    except (urllib.error.URLError, urllib.error.HTTPError, RuntimeError, OSError) as e:
                        backoff = min(cfg.backoff_max_s,
                                      max(cfg.backoff_initial_s, backoff * 2))
                        retry_not_before = time.monotonic() + backoff
                        log.warning("flush failed (%s); backing off %.1fs, %d pending",
                                    e, backoff, buf.pending_count())

                elapsed = time.monotonic() - cycle_start
                sleep_for = max(0.0, cfg.sample_interval_s - elapsed)
                time.sleep(sleep_for)
        except KeyboardInterrupt:
            log.info("interrupt; stopping SPS30 and exiting")
        finally:
            try:
                sps.stop()
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(run())
