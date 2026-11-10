# airmon — Raspberry Pi 4 air quality monitor

## What this project is

A Raspberry Pi 4 reads three environmental sensors, timestamps the readings,
buffers them locally, and POSTs them as JSON to a separate FastAPI service.

The Pi's job is deliberately narrow: **read reliably, timestamp, buffer, send.**

- No analysis, no dashboards, no storage-of-record on the Pi. That is all server-side.
- No business logic on the Pi. "PM2.5 is high, do X" is a server decision.
- When the network is down, buffer to local SQLite and replay on reconnect. Never drop a reading.

The operator (Umut) is a strong software engineer (Python, TypeScript, Linux, SQL)
but a **hardware beginner**. Explain anything electrical plainly. Do not assume
knowledge of voltage levels, pull-ups, or serial internals. The software side does
not need dumbing down.

## Working agreement

- **Go one phase at a time. Stop at the end of each phase and wait for confirmation.**
- **Verification before code.** Prove the OS sees each sensor before writing drivers.
  Prove each driver reads raw values before writing the agent.
- **Flag anything that can damage the Pi or a sensor BEFORE running it, not after.**
- Ask about parts on hand instead of assuming.
- If a decision changes something written in this file, update this file in
  the same commit.

---

## Where things live

The Pi runs the sensor agent and also hosts the FastAPI server + SPA at
`https://airmon.utoker.com` (behind Cloudflare, through Caddy). Deployment
orchestration (systemd units, Caddy, backups, DNS/DDNS, monitoring) lives in
[utoker/homelab](https://github.com/utoker/homelab). This repo owns app code;
that repo owns "where and how it runs".

**Data on the Pi** (single mount, `/srv/data` on a Samsung 860 EVO 500 GB SSD):

- `/srv/data/airmon/buffer.db`: Pi-side offline queue (agent process, `AIRMON_BUFFER_DB`).
- `/srv/data/airmon/server.db`: server-side storage-of-record (FastAPI process, `AIRMON_DB_PATH`).
- `/srv/data/backups/`: nightly `server-*.db.gz` snapshots, mirrored to R2.

The env vars are set on the systemd units in the homelab repo. Nothing lives
under `/home/umut/airmon-data/` any more.

**Retention.** `server.db` keeps tiered raw/minute/hour tables
(`AIRMON_TIER_RAW_DAYS`, `AIRMON_TIER_MINUTE_DAYS`); see
[server/app/rollup.py](server/app/rollup.py) and [README.md](README.md) for the
design. `buffer.db` drops only `sent=1` rows older than
`AIRMON_BUFFER_RETENTION_DAYS`; `sent=0` rows are never touched, because they
are the only durable copy while the network is down.

**`buffer.db` is deliberately NOT backed up.** Every row is duplicated into
`server.db` on successful send, and the agent recreates an empty buffer on
first start.

**Monitoring.** A healthchecks.io dead-man's switch plus a persistent journal;
see [docs/monitoring.md](https://github.com/utoker/homelab/blob/main/docs/monitoring.md)
in the homelab repo.

---

## Hardware (wired 2026-07-14, moved onto a screw-terminal HAT 2026-11-05)

The Pi is a **Raspberry Pi 4 Model B** with 2 GB of RAM. OS is **Raspberry Pi
OS Lite 64-bit** (Debian Trixie). Boot config lives at
**`/boot/firmware/config.txt`** and **`/boot/firmware/cmdline.txt`** (NOT
`/boot/`, that path is stale).

Three sensors. All data lines are 3.3V and safe on the Pi's GPIO. No level
shifters are used anywhere in this build. Two sensors take 5V POWER but output
3.3V LOGIC (verified against datasheets, see below).

### Screw-terminal HAT

Every sensor wire is clamped in an **HCDC RPi GPIO Terminal Block Breakout
HAT** (model D-1297, the version without per-pin LEDs) on the Pi's 40-pin
header. It brings each header pin out to a labeled 3.5 mm screw terminal
(26-16 AWG). There are no ferrules. Each wire is stripped about 10 mm,
twisted, folded back to 5 mm and clamped snug. The SPS30's own cable runs
straight into the terminals, with no extension jumpers or mid-air joints.

- Labels use BCM GPIO names (`IO4` is GPIO4). They're written from the Pi's
  side, so a sensor's TX goes into the Pi's `RXD` terminal.
- There are four blocks of ten, each starting with a power pair. Each sensor
  has its own pair, so no terminal holds two wires:
  - IO17 block: `3V3 GND IO17 IO18 MOSI MISO SCLK CE0 CE1 GND`
  - TXD block: `3V3 GND TXD RXD IO24 IO25 IO5 IO6 IO16 GND`
  - IO23 block: `5V GND IO23 IO22 IDSD IDSC IO12 IO20 IO19 GND`
  - SDA block: `5V GND SDA SCL IO4 IO27 IO21 IO13 IO26 GND`
- The Pi's header pins stick up through the HAT and stay live. Wire only with
  the power off: a screwdriver slipping across them can short 5V onto a GPIO.
- Terminals are 3.5 mm apart, and 5V sits next to GND. After clamping, no bare
  copper may show outside a terminal.
- Still to do: mount everything on one base board (about 9x12 in), with velcro
  for the parts and zip-tie strain relief for the wire bundle near the HAT.

### Power: PiPower UPS

The Pi sits on a **SunFounder PiPower**. It's the original model, hardware V3,
documented at docs.sunfounder.com/projects/pipower-v2. It is not the newer
HAT-style "PiPower 3". The stack, bottom up: acrylic plate, PiPower with its
7.4V 2000 mAh battery pack, the Pi, then the terminal HAT.

- Power path: the official Raspberry Pi 15W supply (5.1V 3A) goes into the
  PiPower's USB-C input. The PiPower's USB-A output goes to the Pi's USB-C.
- While mains power is present, the output passes straight through and the
  battery charges at under 1W, so a full charge takes most of a day. Per its
  docs and a CNX Software review, it switches to battery on mains loss without
  rebooting the Pi. The review measured 3-5 h of runtime. Neither has been
  tested here with a charged battery yet.
- The battery can run the Pi on its own. For wiring work, switch the PiPower
  OFF as well as unplugging the supply.
- **Not done yet: low-battery shutdown.** The PiPower's IO holes are
  unsoldered, so the Pi can't see a low battery, and a long outage still ends
  in a hard power cut. The plan:
  - measure the signal voltage first, because the docs don't say 3.3V or 5V
  - wire IN_DT to `IO17`, LO_DT to `IO27` and GND to `GND`
  - add `dtoverlay=gpio-shutdown` on GPIO27

  After a low-battery shutdown, the Pi likely stays halted if mains returns
  before the battery runs flat. Toggle the PiPower switch to restart it.

### Sensor 1 — Sensirion SPS30 (particulate matter) — PRIMARY

- Measures PM1.0, PM2.5, PM4.0, PM10 mass concentrations, plus number
  concentrations and typical particle size.
- **Interface: UART** (chosen over its I2C mode deliberately). Sensirion's
  datasheet says I2C needs cables under 10 cm; this sensor sits on a longer
  cable near a fan array (EMI source), so UART is the robust choice.
- **UART3** on the Pi: GPIO4 (phys 7) and GPIO5 (phys 29).
- Power 5V, logic 3.3V (datasheet output-high max is 3.37V, so Pi-safe).
- Baud **115200**, 8N1. Protocol is **SHDLC** (framed, byte-stuffed, checksummed).
- Fan life 8+ years, self-cleaning weekly. No fan-management needed for v1.
- The 5-wire cable that shipped with it, decoded from the connector
  (red and black at opposite ends confirm orientation):

  | Wire   | SPS30 pin | Function         | HAT terminal                  |
  | ------ | --------- | ---------------- | ----------------------------- |
  | red    | 1 VDD     | 5V power         | `5V`, SDA block               |
  | white  | 2 RX      | sensor input     | `IO4` (GPIO4/TXD3, phys 7)    |
  | purple | 3 TX      | sensor output    | `IO5` (GPIO5/RXD3, phys 29)   |
  | teal   | 4 SEL     | interface select | **NOT CONNECTED**             |
  | black  | 5 GND     | ground           | `GND`, SDA block              |

  SEL (teal) MUST stay disconnected. Floating = UART mode. Its absolute max is
  4.0V; putting 5V on it destroys the sensor. It should be taped off.

### Sensor 2 — Winsen MH-Z19B (CO2) — SECONDARY, optional-but-kept

- NDIR CO2, 0 to 5000 ppm. Green PCB (the good variant; black PCBs are clones).
- **Interface: UART**, on **UART0** (PL011): GPIO14 (phys 8, TXD) and
  GPIO15 (phys 10, RXD).
- Power 5V, logic 3.3V (internal 5V-to-3.3V regulator on the UART lines).
- Baud **9600**, 8N1. Fixed 9-byte command/response frames.
- Header pins were soldered into 4 of the 7 holes: Vin, GND, Tx, Rx.
- Wiring:

  | Board pin | HAT terminal                   |
  | --------- | ------------------------------ |
  | Vin       | `5V`, IO23 block               |
  | GND       | `GND`, IO23 block              |
  | Tx        | `RXD` (GPIO15/RXD0, phys 10)   |
  | Rx        | `TXD` (GPIO14/TXD0, phys 8)    |

- **Gotchas that produce silent bad data:**
  - ~3 minute warm-up after power-on. Readings before that are unreliable and
    must be tagged, not published as truth.
  - ABC (Automatic Baseline Correction) is ON by default. It assumes the lowest
    CO2 seen in any 24h window is 400 ppm and re-zeros to it. Fine for a room
    ventilated daily; drifts in a sealed room. Leave ON for v1, make it a config flag.

### Sensor 3 — GY-21 (temperature + humidity) — ESSENTIAL for PM compensation

- Board carries one of Si7021 / SHT21 / HTU21D. All three are at **I2C 0x40**,
  wire identically, and **use the identical RH/temp conversion formulas**, so the
  driver does NOT need to branch on chip type. Identifying the exact chip (via its
  electronic serial number) is a nice-to-have for logging only, not required.
- **Interface: I2C** bus 1: GPIO2 SDA (phys 3), GPIO3 SCL (phys 5).
- Power 3.3V. This board takes power from a **`3V3`** terminal, NEVER a `5V`
  one: on 5V its pull-ups can push 5V into the Pi's SDA/SCL pins.
- Wiring:

  | Board pin | HAT terminal           |
  | --------- | ---------------------- |
  | VIN       | `3V3`, IO17 block      |
  | GND       | `GND`, IO17 block      |
  | SDA       | `SDA` (GPIO2, phys 3)  |
  | SCL       | `SCL` (GPIO3, phys 5)  |

- A loose header joint or terminal clamp causes intermittent I2C, which looks
  exactly like a software bug. If `i2cdetect` is flaky, suspect those first.
- **Mounting note (physical, later):** keep this sensor away from the Pi body.
  The Pi runs warm and will bias temperature high, which corrupts RH, which
  corrupts PM compensation. Put it on a short lead away from the Pi and the SPS30 exhaust.

### Not used

- BMP180 (pressure), BH1750 (light): both dropped. Irrelevant to air quality,
  and BMP180 has no maintained driver. Do not wire them.
- ANAVI Infrared pHAT: set aside. Its UART header is 3.3V-only (can't power the
  MH-Z19B) and it has no fan-control hardware. Build on the Pi header directly.

### I2C address map (no conflicts)

```
0x40  GY-21 (temp/humidity)   <- only device on the I2C bus
0x68  DS3231 RTC              <- planned (README "Future work"), not wired
```

Both PM and CO2 sensors are on UART, so the I2C bus has exactly one device.
Cleanest possible bus. Do not add pull-up resistors; the Pi has them built in.

---

## PHASE 4 — Pi OS setup and hardware verification (PASSED 2026-07-14)

Kept here as the canonical bring-up procedure. If the SD card is ever wiped
or the hardware is redone, this is the runbook. All four checks passed on
the current Pi and its serial-device mapping is captured in the memory file
`uart_device_mapping.md`. Commands that touch i2c/serial run ON the Pi.

### 4.1 Ensure interfaces are enabled

Append to `/boot/firmware/config.txt` (idempotent; check before adding):

```ini
# --- air quality monitor ---
dtparam=i2c_arm=on
enable_uart=1
dtoverlay=disable-bt   # frees the real PL011 UART0 onto GPIO14/15
dtoverlay=uart3        # wakes the Pi 4's second UART on GPIO4/5
```

Why `disable-bt`: without it, GPIO14/15 get the mini-UART whose baud rate drifts
with CPU load, so the MH-Z19B works at idle and corrupts under load.

### 4.2 Free the serial port from the login console

`/boot/firmware/cmdline.txt` is a SINGLE line. Remove `console=serial0,115200`
and any `console=ttyAMA0,115200`. Keep `console=tty1`. Do not add a newline.

Then:

```bash
sudo systemctl disable --now hciuart 2>/dev/null || true
sudo systemctl disable --now serial-getty@ttyAMA0.service 2>/dev/null || true
sudo systemctl disable --now serial-getty@ttyS0.service 2>/dev/null || true
sudo usermod -aG dialout,i2c,gpio "$USER"
sudo reboot
```

### 4.3 Verify — all four must pass

```bash
# a) pins are in the right mode
pinctrl get 2,3,4,5,14,15
#   expect: 2=SDA1 3=SCL1 4=TXD3 5=RXD3 14=TXD0 15=RXD0
#   If GPIO4 shows 'input'/'GPIO_GCLK' not TXD3: known uart3 half-apply bug. STOP.

# b) the I2C sensor is present
i2cdetect -y 1
#   expect 0x40 in the grid. Missing => unsoldered pins, swapped SDA/SCL, or wrong VIN pin.

# c) map ttyAMA device names to hardware UARTs (names are NOT stable across kernels)
for d in /dev/ttyAMA*; do n=$(basename "$d");
  echo "$n -> $(basename "$(readlink -f /sys/class/tty/$n/device)")"; done
#   fe201000.serial = UART0 = MH-Z19B
#   fe201600.serial = UART3 = SPS30
#   RECORD which /dev/ttyAMA* maps to which address. These are hardcoded into config later.
#   Do not assume ttyAMA3 == uart3; it usually isn't.

# d) console really left the port
cat /proc/cmdline   # must contain NO console=serial0 and NO console=ttyAMA0
```

Report all four outputs before proceeding.

---

## PHASE 5 — Verification script, then the agent (SHIPPED)

Both deliverables below shipped. Section 5.1's driver choice landed on
hand-rolled SHDLC; 5.3's `verify.py` lives at `pi/verify.py`; 5.4's agent
lives at `pi/agent.py` with `pi/buffer.py`, `pi/config.py`, and the drivers
under `pi/drivers/`. The server companion is `server/app/` with `main.py`,
`schema.py`, `db.py`, `rollup.py`, `maintenance.py`. Systemd units are in
the [utoker/homelab](https://github.com/utoker/homelab) repo. See the
"Where things live" section at the top and README.md for what shipped
beyond the original plan.

### 5.1 Driver approach

Prefer **stdlib + `pyserial` + `smbus2`**, hand-rolled drivers, over the Blinka/
CircuitPython stack. Rationale: this box runs one job unattended; Blinka's value is
cross-platform portability we don't need, and it drags in a dependency tree that
breaks on OS upgrades. The GY-21 and MH-Z19B protocols are trivial to hand-roll.

The SPS30's SHDLC framing (byte-stuffing + checksum) is the one non-trivial one.
Two acceptable options, pick after checking PyPI live for current maintenance:

- Sensirion's own maintained UART driver package, if it installs cleanly without
  pulling in a large tree, OR
- a hand-rolled SHDLC layer (well-specified below). Either is fine; state the choice.

Use a venv: `python3 -m venv .venv && . .venv/bin/activate`.

### 5.2 Protocol reference (so drivers don't guess)

**MH-Z19B (9600 8N1):**

- Read CO2 command (9 bytes): `FF 01 86 00 00 00 00 00 79`
- Response (9 bytes): `FF 86 HI LO ...`; CO2 ppm = HI\*256 + LO
- Checksum on a 9-byte frame: `0xFF - (sum bytes[1..8]) + 1`, compare to byte[8]. Reject frames that fail.
- ABC off: `FF 01 79 00 00 00 00 00 86` ABC on: `FF 01 79 A0 00 00 00 00 E6`

**SPS30 (115200 8N1, SHDLC):**

- Frame: `7E ADR CMD LEN DATA... CHK 7E`, ADR=0x00.
- Byte-stuff inside frame: 7E->7D 5E, 7D->7D 5D, 11->7D 31, 13->7D 33 (un-stuff on read).
- CHK = bitwise-NOT of (LSB of sum of ADR,CMD,LEN,DATA).
- Start Measurement: CMD 0x00, DATA `[0x01, fmt]`; fmt 0x03 = big-endian float (recommended), 0x05 = uint16.
- Read Measured Values: CMD 0x03. Float format returns 40 bytes = 10 big-endian
  float32: PM1.0, PM2.5, PM4.0, PM10 (ug/m3), then 5 number-concentrations, then typical size (um).
- Stop Measurement: CMD 0x01. Read serial number: CMD 0xD0.
- Sequence: open port -> Start Measurement -> poll Read Measured Values (~1 Hz) -> parse.

**GY-21 / Si7021 / HTU21D / SHT21 (I2C 0x40):**

- Soft reset 0xFE. Measure temp (no-hold) 0xF3; measure RH (no-hold) 0xF5.
- Read 3 bytes (MSB, LSB, CRC); mask the low 2 status bits of the 16-bit word.
- `RH% = -6 + 125 * raw / 65536`. `TempC = -46.85 + 175.72 * raw / 65536`.
- No-hold mode needs a wait between command and read (temp ~11ms, RH ~15ms; be generous).
- Formulas are identical for all three chips.

### 5.3 First deliverable: `verify.py`

A dead-simple script that reads each sensor ONCE and prints raw values, so the
operator can confirm wiring end-to-end before any real logic exists. It must:

- Read device paths from config/env (the fe201000 / fe201600 mapping from Phase 4).
- Read GY-21 temp + RH, MH-Z19B CO2, SPS30 all PM channels, once each.
- Print raw values with labels. Fail loudly and specifically per sensor (which one,
  what went wrong) rather than one opaque traceback.
- Note that the MH-Z19B may read ~400-500 ppm or unstable if within the 3-min warmup.

STOP after verify.py works on real hardware. Do not build the agent until the
operator confirms all three sensors return sane raw numbers.

### 5.4 Second deliverable: the agent

Only after verify.py passes. Requirements:

- **Read loop** at a configurable interval. Timestamp every reading in UTC ISO-8601.
- **SQLite buffer**: persist every reading with a sent/unsent flag. This is the
  offline safety net; a reading is only marked sent after the server 2xx's.
- **Batched POST with retry**: send unsent rows in batches to the FastAPI endpoint,
  exponential backoff on failure, mark sent on success. Survive network outages
  and replay on reconnect. Never lose or duplicate a reading (idempotency key per reading).
- Tag readings taken during MH-Z19B warmup as unstable rather than dropping them.
- Config via env/file: server URL, interval, the two serial device paths, ABC flag.
- Keep it modular: `drivers/`, a buffer module, an agent entrypoint.
- **systemd** unit so it survives reboots (`Restart=always`, `After=network-online.target`,
  run as the user, venv python). Provide the unit file and enable instructions.

Repo is a monorepo. The Pi's runtime job stays narrow (read/timestamp/buffer/send),
but the FastAPI server and the SPA live alongside it here so the JSON schema stays
in one place:

```
airmon/
  pi/
    drivers/{sps30.py, mhz19b.py, gy21.py}
    verify.py
    buffer.py         # SQLite read/write, sent-flag, batch fetch
    agent.py          # read loop + POST + retry
    maintenance.py    # buffer.db prune (sent+aged), invoked by systemd timer
    config.py         # env/file config
    requirements.txt  # pyserial, smbus2
  server/
    app/{main.py, schema.py, db.py, rollup.py, maintenance.py, purifier.py}
    tests/            # pytest; requirements-dev.txt
    requirements.txt  # fastapi, uvicorn
  web/                # Vite + React + Recharts SPA
```

Deploy `pi/` to the Pi (rsync target `/home/umut/airmon/`), `server/` to
`/home/umut/airmon-server/`, and the built `web/dist/` to `/home/umut/airmon-web/`.
The git checkout on the Pi lives at `/home/umut/airmon-repo/` on purpose:
`~/airmon` is a rsync target and would erase the checkout under itself.
`scripts/deploy-airmon.sh` in the homelab repo does the whole thing.

**Deployment orchestration for the Pi (systemd units, Caddy reverse proxy, DNS/DDNS,
security, backups, retention timers) lives in a separate repo: [utoker/homelab](https://github.com/utoker/homelab).**
This repo owns app code; that repo owns "where and how it runs".

The JSON payload shape is LOCKED (2026-07-14): a batch of readings, each with a
reading id (uuid, idempotency key), captured_at (UTC ISO-8601), and flat per-sensor
fields (pm1/pm25/pm4/pm10, co2_ppm + co2_warming flag, temp_c, rh_pct). The
pydantic model in `server/app/schema.py` is the source of truth.

### 5.5 Known failure modes to check before blaming code

- Flaky/absent 0x40 on i2cdetect -> unsoldered GY-21 header pins.
- MH-Z19B garbage under load -> `disable-bt` overlay missing (mini-UART clock drift).
- Serial device "busy"/echoes login noise -> serial console not fully removed from cmdline.txt.
- Wrong ttyAMA number -> use the fe201000/fe201600 mapping, not the UART index.
- SPS30 returns nothing -> SEL (teal) accidentally connected, or TX/RX swapped, or still in Idle (Start Measurement not sent).

---

## PHASE 6: Purifier fan control (IN PROGRESS)

Goal: the server sets a DIY air purifier's fan speed from PM readings, through
an ESP32 that sits at the purifier. Everything below is confirmed with Umut.

### 6.1 Hardware

**Purifiers.** Two DIY builds, each PC fans + a MERV-13 filter, each with
3x ARCTIC P14 Pro PST fans daisy-chained via PST (a pass-through socket on
each fan). One PWM wire drives all three fans; tach (the RPM signal) comes
from the head fan only. The PST chain replaces the hub an earlier plan said
to buy.

Fan specs (each): 12V, 0.35 A / 4.2 W max, 400-2500 RPM, **0 RPM below 5%
PWM duty** (the fans fully stop). Three fans draw ~1.05 A at full speed,
well inside a 12V 2A adapter.

- **Purifier A:** runs on a knob-controlled 4-pin PWM hub + 12V 2A adapter.
  A knob hub has no input a computer can drive. Left as is for now; it gets
  the same setup as B later, using a spare ESP32.
- **Purifier B:** new, built for control from the start. **This phase targets B.**
  Its filter is MERV-13 with a carbon layer.

**Placement.** Purifier B, the Pi with all three sensors, and the cats'
Litter-Robot 5 share the bedroom. Purifier A is in the living/work room, so
the PM readings, and any curve built on them, describe the bedroom only.

**Controller.** ESP32 DevKit V1 (ESP-WROOM-32, CP2102 USB chip, micro-USB) at
the purifier, running ESPHome over Wi-Fi. The ESPHome config goes in `purifier/`.

- D26: PWM out, 25 kHz (the standard frequency for 4-pin PC fans).
- D33: tach in, held at 3.3V by the ESP32's internal pull-up (no resistor).
  D33 rather than D27 because on the purifier board the hole next to D27
  sits beside the 1k's leg.
- D25: unused; earlier "dead pin" reading was a ground fault, not the pin.

The Pi's own GPIO is not used for fan control.

**Power.**

- Fans: their own 12V 2A adapter, through a panel-mount barrel jack.
- ESP32: a separate USB charger.
- Grounds joined: the 12V adapter's negative and an ESP32 GND pin connect
  together. A signal voltage only means something relative to a ground, so
  without this the fans cannot read the ESP32's PWM and the ESP32 cannot read
  the tach.
- Wire-to-wire joins use Wago 221 lever connectors.

### 6.2 Hard safety rules (state these before any wiring step)

- Never power fans from the Pi or the ESP32.
- 12V never touches an ESP32 pin.
- The 12V side and the ESP32 share a ground.
- ESP32 pins are 3.3V max. Measure the fans' PWM and tach idle voltages with a
  multimeter before wiring them to the ESP32.
  - If PWM idles above 3.3V, drive it through a transistor (open-drain: the
    ESP32 switches the transistor, the transistor pulls the fan's line to
    ground, and the ESP32 pin never sees the fan's voltage).
  - Tach only ever pulls its line low, so something must pull it high. Pull it
    up to 3.3V, never higher.
- Power the ESP32 from USB. Never feed 12V into VIN.
- Never have the ESP32 plugged into a PC while the 12V wiring is attached.

### 6.3 Control policy

- Policy stays server-side. The server computes the target duty from PM and
  Litter-Robot visits, and the ESP32 polls the server for it every 30 s at
  `http://192.168.1.15:8081/api/purifier/b/target` (Caddy's LAN-only HTTP
  listener, set up in the homelab repo).
- The ESP32 ramps toward the target by at most 10 points per poll, in either
  direction. It boots at the fallback duty and holds it until the first good
  poll.
- If the ESP32 cannot reach the server, it falls back to a **fixed** duty
  (40%), not a cached curve. The server and the PM sensors are on the same Pi, so no
  server means no PM data for a curve to act on. It falls back after 4 failed
  polls in a row (~2 min: error, non-200, or bad JSON); until then it holds
  its current speed.
- Noise: the room is occupied, so the curve has a quiet always-on floor
  (25%), never jumps straight to 100%, and treats anything under 5% as a
  deliberate "off" (the fans stop there). The curve never returns "off";
  turning the fans off is manual.
- Goal: keep PM2.5 below 1 ug/m3.
- Curve ([server/app/purifier.py](server/app/purifier.py)): piecewise-linear
  on the mean PM2.5 over the last **5 minutes**, through (PM2.5 ug/m3, duty %)
  points (0.5, 25), (1, 40), (2, 60), (5, 85), (10, 100). At or below 0.5 it
  holds at 25%; at or above 10 it holds at 100%.
- No PM2.5 readings in the 5-minute window (sensor or agent down, server up):
  the server returns a fallback of **40%** (`AIRMON_PURIFIER_FALLBACK_PCT`)
  with `reason: "stale"`.
- Litter-Robot boost: litter smell is gas, which the SPS30 can't see (PM2.5
  stayed flat or fell after 5 of 6 cat visits on 2026-11-10), so Home
  Assistant reports the visit instead. Its `litter_boost.yaml` package in the
  homelab repo POSTs `{"minutes": 30}` when the Litter-Robot's status turns
  `cst` (cat in), and `{"minutes": 10}` when it returns to `rdy` after the
  clean cycle. Each POST replaces the running boost rather than extending it;
  0 clears it.
- While a boost runs, the target is **100%**, or **70%** from 23:00 to 07:00
  local time because the purifier shares the bedroom, with `reason: "boost"`.
  A boost never lowers the duty, so a PM spike still goes past 70% at night. The ESP32's normal ramp gets there (about 4 minutes from
  the floor), so the target still never jumps straight to 100%.
- Boosts live in server memory (uvicorn runs one worker). A server restart
  drops a boost and the curve takes over.
- Endpoints: `GET /api/purifier/{a|b}/target`, no auth, same curve for both
  purifiers. `POST /api/purifier/{a|b}/boost`, reachable only on loopback:
  Caddy rejects POST on the public site and on :8081.

### 6.4 Steps and status

| Step | What                                                          | Status                                                |
| ---- | ------------------------------------------------------------- | ----------------------------------------------------- |
| 1    | Parts check                                                   | DONE 2026-10-24                                       |
| 2    | ESP32 alone on Wi-Fi                                          | DONE 2026-10-24                                       |
| 2b   | Own baseline ESPHome firmware over Wi-Fi, no pins configured  | DONE 2026-10-25                                       |
| 3    | Measure fan PWM/tach idle voltages with a multimeter          | DONE 2026-10-27                                       |
| 4    | Wire PWM + tach; ESP32 alone sets speed and reads RPM         | DONE 2026-10-31 (speed); tach DONE 2026-11-01         |
| 5    | Server: target-duty endpoint + noise-aware curve              | DONE 2026-10-31 (deployed)                            |
| 6    | Close the loop; test the fallback by cutting the Pi's network | DONE 2026-10-31 (fallback tested by blocking :8081)   |
| 7    | Boost B on Litter-Robot visits, triggered by Home Assistant   | BUILT 2026-11-10, not deployed                        |

Board state: runs `purifier/purifier-b.yaml` (ESPHome 2026.9.1), hostname
`purifier-b.local`, 192.168.1.98 via DHCP (not reserved, so it can change),
MAC 68:09:47:e0:d5:1c. Updates go over Wi-Fi; see `purifier/README.md`.

### 6.5 Gotchas

- On Windows, the board needs the Silicon Labs CP210x driver. Without it,
  Chrome's port picker shows only the motherboard's COM1, which connects and
  then stays silent.
- To test the fallback, don't take the Pi off the network: that cuts SSH,
  the public sites, and LAN DNS (AdGuard). Drop just the ESP32's traffic to
  :8081 instead, which looks the same to the ESP32 (each poll times out):
  `sudo ufw insert 1 deny from <esp32-ip> to any port 8081 proto tcp`, then
  `sudo ufw delete deny from <esp32-ip> to any port 8081 proto tcp`.
  Expect 4 `Poll failed` lines (~2 min), Control `fallback`, a ramp toward
  40%, and Control `server` within 30 s of removing the rule.
