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
- Style: no em dashes in prose.

---

## Hardware (already wired, pending verification)

The Pi is a **Raspberry Pi 4 Model B**. OS is **Raspberry Pi OS Lite 64-bit**
(Debian Trixie). Boot config lives at **`/boot/firmware/config.txt`** and
**`/boot/firmware/cmdline.txt`** (NOT `/boot/`, that path is stale).

Three sensors. All data lines are 3.3V and safe on the Pi's GPIO. No level
shifters are used anywhere in this build. Two sensors take 5V POWER but output
3.3V LOGIC (verified against datasheets, see below).

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

  | Wire   | SPS30 pin | Function        | Lands on Pi        |
  |--------|-----------|-----------------|--------------------|
  | red    | 1 VDD     | 5V power        | phys 4 (5V)        |
  | white  | 2 RX      | sensor input    | phys 7  (GPIO4/TXD3) |
  | purple | 3 TX      | sensor output   | phys 29 (GPIO5/RXD3) |
  | teal   | 4 SEL     | interface select| **NOT CONNECTED**  |
  | black  | 5 GND     | ground          | phys 9 (GND)       |

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

  | Board pin | Lands on Pi         |
  |-----------|---------------------|
  | Vin       | phys 2 (5V)         |
  | GND       | phys 6 (GND)        |
  | Tx        | phys 10 (GPIO15/RXD0) |
  | Rx        | phys 8  (GPIO14/TXD0) |

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
- Power 3.3V. This board takes power from **phys 1 (3V3)**, NOT phys 2.
- Wiring:

  | Board pin | Lands on Pi        |
  |-----------|--------------------|
  | VIN       | phys 1 (3V3)       |
  | GND       | phys 14 (GND)      |
  | SDA       | phys 3 (GPIO2)     |
  | SCL       | phys 5 (GPIO3)     |

- Header pins may not be soldered yet. Unsoldered pins cause intermittent I2C,
  which looks exactly like a software bug. If `i2cdetect` is flaky, suspect this first.
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
```
Both PM and CO2 sensors are on UART, so the I2C bus has exactly one device.
Cleanest possible bus. Do not add pull-up resistors; the Pi has them built in.

---

## Future phase (do NOT build yet, just don't design it out)

A separate custom air purifier (PC fans + MERV-13) will eventually be driven by
the Pi to ramp fan speed when PM is high. Reserved for that, keep free:
- GPIO12 (phys 32), GPIO13 (phys 33): hardware PWM for 4-pin fans (25 kHz).
- GPIO16 (phys 36): fan tach input.

Hard rules for that future phase (state them when we get there):
- PC fans are 12V. Never power them from the Pi. Separate 12V supply, common ground.
- A fan's tach and PWM lines idle at 5V or 12V. Never wire them straight to a GPIO.
  Measure idle voltage first; if above 3.3V, use a transistor/level shift.
- The user's "Ransanx K11" hub is knob-controlled with no motherboard PWM input,
  so the Pi cannot drive it. It will be replaced with a passive 4-pin PWM hub. Don't buy anything yet.
- Policy (the PM-to-fan-speed curve) stays server-side and is handed to the Pi in
  the POST response; the Pi only executes a cached curve so it still works offline.

---

## PHASE 4 — Pi OS setup and hardware verification (DO THIS FIRST)

The wiring is done but NOT yet verified. Do not write any driver until every
check below passes. Commands that touch i2c/serial run ON the Pi.

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

## PHASE 5 — Verification script, then the agent

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
- Response (9 bytes): `FF 86 HI LO ...`; CO2 ppm = HI*256 + LO
- Checksum on a 9-byte frame: `0xFF - (sum bytes[1..8]) + 1`, compare to byte[8]. Reject frames that fail.
- ABC off: `FF 01 79 00 00 00 00 00 86`   ABC on: `FF 01 79 A0 00 00 00 00 E6`

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
- RH% = -6 + 125 * raw / 65536.  TempC = -46.85 + 175.72 * raw / 65536.
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

Suggested layout (Claude Code owns final structure):
```
airmon/
  drivers/{sps30.py, mhz19b.py, gy21.py}
  verify.py
  buffer.py       # SQLite read/write, sent-flag, batch fetch
  agent.py        # read loop + POST + retry
  config.py       # env/file config
systemd/airmon.service
```

The JSON payload shape should be simple and server-friendly, e.g. a batch of
readings each with: reading id (uuid), captured_at (UTC ISO-8601), and per-sensor
fields (pm1/pm25/pm4/pm10, co2_ppm + co2_warming flag, temp_c, rh_pct). Confirm the
exact schema with the operator, since the FastAPI service is being written separately.

### 5.5 Known failure modes to check before blaming code
- Flaky/absent 0x40 on i2cdetect -> unsoldered GY-21 header pins.
- MH-Z19B garbage under load -> `disable-bt` overlay missing (mini-UART clock drift).
- Serial device "busy"/echoes login noise -> serial console not fully removed from cmdline.txt.
- Wrong ttyAMA number -> use the fe201000/fe201600 mapping, not the UART index.
- SPS30 returns nothing -> SEL (teal) accidentally connected, or TX/RX swapped, or still in Idle (Start Measurement not sent).