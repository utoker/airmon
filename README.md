# airmon

An end-to-end air quality monitor for my apartment. A Raspberry Pi 4 samples
three environmental sensors every 5 seconds and streams the readings to a
FastAPI service on the same Pi, which stores them in SQLite and serves a
React + Recharts dashboard.

Live at [airmon.utoker.com](https://airmon.utoker.com) (Cloudflare-proxied,
Caddy-terminated, running on the Pi itself).

I built this partly to know what I'm breathing and partly to practice building
a system that has to keep working when I am not looking at it: unattended for
months, tolerant of network outages, and cheap to operate long-term.

## What it measures

| Sensor | Metric | Interface |
| --- | --- | --- |
| Sensirion SPS30 | PM1.0 / PM2.5 / PM4.0 / PM10 (ug/m3) | UART3 (SHDLC, 115200 baud) |
| Winsen MH-Z19B | CO2 (ppm) | UART0 (9600 baud, 9-byte frames) |
| Si7021 / SHT21 / HTU21D (GY-21) | Temperature, relative humidity | I2C bus 1, address 0x40 |

## Architecture

```
+----------------+       HTTPS +           +----------------+
|  Raspberry Pi  |       POST /api/        |    Browser     |
|                | readings (JSON)         |                |
|  agent.py -----+---> FastAPI --> SQLite  |  React SPA <---+--- Caddy
|      |         |     rollup / prune      |  Recharts      |    (TLS + static)
|  buffer.db     |     GET /api/readings   |                |
|  (offline)     |                         |                |
+----------------+                         +----------------+
        ^                                          |
        |         all on the same Pi 4             |
        +------------------------------------------+
```

The Pi's job is deliberately narrow: **read, timestamp, buffer, send**. It
does no analysis and holds no storage-of-record. If the network drops, every
reading lands in a local SQLite queue and is replayed on reconnect with a
UUID idempotency key, so nothing is lost and nothing is double-inserted.

The FastAPI service owns storage, aggregation, and the read API. The SPA is
static assets served by the same process (or by Caddy in production).

## Interesting engineering decisions

- **Hand-rolled drivers over Blinka / CircuitPython.** This box runs one job
  unattended for years. Blinka's value is portability I do not need, and its
  dependency tree tends to break on OS upgrades. The GY-21 and MH-Z19B
  protocols are trivial and the SPS30's SHDLC (byte-stuffed, checksummed
  frames) is spelled out in the datasheet. Three small files in
  [pi/drivers/](pi/drivers/), no wheels to babysit.

- **SQLite as an offline queue.** [pi/buffer.py](pi/buffer.py) persists every
  reading with a `sent` flag. Readings are only marked sent after the server
  returns 2xx. On restart the queue is intact. A separate retention loop
  drops rows older than 7 days but only if `sent=1`, so unsent rows survive
  even long outages.

- **Tiered downsampling instead of a metrics database.** Storing raw 5-second
  samples forever would grow unbounded, but I wanted the full-resolution
  history for recent windows and something durable for long ranges. The
  server keeps three tables ([server/app/rollup.py](server/app/rollup.py)):
  - `readings`: raw 5s samples, kept 14 days
  - `readings_minute`: per-minute avg/min/max/count, kept 90 days
  - `readings_hour`: per-hour avg/min/max/count, kept forever

  Hour storage is ~2.3 MB/year, so the database settles near 100 MB
  indefinitely rather than growing without bound.

- **Verify-before-prune.** The daily maintenance job
  ([server/app/maintenance.py](server/app/maintenance.py)) rolls up raw rows
  into minute and hour buckets, then samples random aggregate rows and
  recomputes them from raw. If any sample mismatches, that run refuses to
  prune. Aggregates are only trusted after they have been proven faithful.

- **Fresh aggregates on the fly.** The daily rollup would leave the chart
  stale for up to 24 hours in aggregate tiers. The read API detects the gap
  between the last rolled-up bucket and now, aggregates raw rows on the fly
  for that portion, and stitches it onto the pre-rolled history so the 6h /
  24h / 7d views stay live-updating.

- **Auto tier selection.** The API picks the finest tier whose point count
  fits a ~2000-point cap. The client just asks for a time range; the chosen
  resolution comes back in the response so the UI can label it.

- **App code vs. ops split into two repos.** This repo is app code. The
  systemd units, Caddy config, DNS, DDNS, and R2 backup wiring live in a
  separate homelab repo. Every commit here can be reasoned about without
  worrying about deployment concerns, and vice versa.

## Repo layout

```
pi/
  drivers/{sps30,mhz19b,gy21}.py   hand-rolled sensor drivers
  agent.py                         read loop + POST + retry + backoff
  buffer.py                        SQLite offline queue
  maintenance.py                   buffer prune (sent + aged)
  verify.py                        one-shot bring-up sanity check
  config.py                        env-driven config
server/
  app/main.py                      FastAPI: POST /readings, GET /readings
  app/schema.py                    Pydantic Reading + ReadingBatch
  app/db.py                        SQLite connection + schema init
  app/rollup.py                    tiered aggregation, verify_bucket
  app/maintenance.py               daily rollup + verify + prune
web/
  src/{App,api}.tsx                React 19 + Recharts SPA
CLAUDE.md                          project brief, phases, gotchas
```

## Running locally

The three sensors are the interesting part; without them the agent has
nothing to read. But the server and SPA run fine against any SQLite file
that follows the schema.

Server:
```bash
cd server
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Web:
```bash
cd web
npm install
npm run dev
```

Pi agent (only useful on real hardware with the wiring in
[CLAUDE.md](CLAUDE.md)):
```bash
cd pi
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
AIRMON_SERVER_URL=http://127.0.0.1:8000/api python3 agent.py
```

## Configuration

All runtime config is environment variables. The interesting ones:

| Variable | Default | What it controls |
| --- | --- | --- |
| `AIRMON_SAMPLE_INTERVAL_S` | `5` | Sensor sampling cadence |
| `AIRMON_MHZ19B_WARMUP_S` | `180` | Tag CO2 as unstable for this long after boot |
| `AIRMON_MHZ19B_DEVICE` | `/dev/ttyAMA0` | Serial device for CO2 sensor |
| `AIRMON_SPS30_DEVICE` | `/dev/ttyAMA3` | Serial device for PM sensor |
| `AIRMON_BUFFER_DB` | `~/.local/state/airmon/buffer.db` | Pi-side offline queue |
| `AIRMON_DB_PATH` | (server side) | Server storage-of-record |
| `AIRMON_TIER_RAW_DAYS` | `14` | Retention for 5s samples |
| `AIRMON_TIER_MINUTE_DAYS` | `90` | Retention for per-minute aggregates |
| `AIRMON_BUFFER_RETENTION_DAYS` | `7` | Retention for sent rows in buffer.db |

## Hardware notes

The full wiring diagram, gotchas, and bring-up runbook live in
[CLAUDE.md](CLAUDE.md). Highlights worth calling out:

- The SPS30's `SEL` pin must stay floating for UART mode. Wiring it to 5V
  destroys the sensor. It is taped off inside the enclosure.
- The MH-Z19B needs `dtoverlay=disable-bt` so it lands on the real PL011
  UART, not the mini-UART whose clock drifts with CPU load and silently
  corrupts readings under load.
- The Pi has built-in I2C pull-ups; do not add external ones.
- The GY-21 is on a lead away from the Pi body. The Pi runs warm and would
  bias the temperature reading, which corrupts RH, which corrupts any future
  PM humidity compensation.

## Future work

Reserved but not built: a custom PC-fan-plus-MERV-13 air purifier driven by
the Pi. The fan curve is intentionally kept server-side and shipped to the
Pi in the POST response, so the policy can change without a firmware push
and the Pi still executes a cached curve when offline. GPIO12/13/16 are
reserved for hardware PWM and tach.
