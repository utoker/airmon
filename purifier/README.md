# purifier

ESPHome firmware for the purifier fan controllers (CLAUDE.md, Phase 6).
`purifier-b.yaml` drives the fans (PWM on GPIO26) and follows the airmon
server: every 30 s it fetches a target duty and ramps toward it, at most 10
points per poll. After 4 failed polls in a row (~2 min) it ramps toward a
fixed 40% fallback instead. It boots at 40% and holds that until the first good
poll. It also reads the head fan's tach (GPIO33, internal pull-up) and
reports fan RPM.

All commands run from this directory.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp secrets.example.yaml secrets.yaml   # then fill it in
```

## Compile

```bash
.venv/bin/esphome compile purifier-b.yaml
```

The first compile downloads the ESP-IDF toolchain and takes several minutes.
Output lands in `.esphome/build/purifier-b/build/`:
- `firmware.ota.bin`: what an over-the-air install sends.
- `firmware.factory.bin`: full image for a USB flash through
  [web.esphome.io](https://web.esphome.io) -> Install. Only needed if Wi-Fi
  updates stop working.

## Install over Wi-Fi

```bash
.venv/bin/esphome run purifier-b.yaml --device <ip>
```

Use the IP, not `purifier-b.local`: mDNS often doesn't resolve from WSL. To
find the IP, ask the Pi:

```bash
ssh airmon getent hosts purifier-b.local
```

## Test the fans

Open `http://<ip>/` in a browser on the home network. The **Fans** row has an
on/off toggle and a speed slider (1-100%). The fans stop below 5%.

The page also shows **Control** (`server` while polls succeed, `fallback`
before the first good poll and after 4 failures in a row) and **Target %**
(the duty the fans are ramping toward), and **Fan RPM** (the head fan's
speed, updated every 10 s; roughly 400-2500 RPM, 0 when the fans are stopped).

**Manual changes don't stick.** The next poll, within 30 s, ramps the fans
from wherever you left them back toward the target, and that includes turning
them off. To hold a speed by hand, install firmware without the `interval:`
block.

## Logs

```bash
.venv/bin/esphome logs purifier-b.yaml --device <ip>
```

## Recovery

If the board can't join Wi-Fi for 90 s, it opens a hotspot named
`Purifier-B Fallback` (password: `fallback_ap_password` in `secrets.yaml`).
Join it from a phone; the captive portal at 192.168.4.1 lets you enter new
Wi-Fi credentials or upload a firmware `.bin`.
