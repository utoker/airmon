# purifier

ESPHome firmware for the purifier fan controllers (CLAUDE.md, Phase 6).
`purifier-b.yaml` sets fan speed (PWM on GPIO26) from a built-in web page.
Tach (RPM) is not configured yet.

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

On a freshly flashed board the page can show Fans ON at speed 0, which means
stopped. Move the slider; the speed you set survives reboots.

## Logs

```bash
.venv/bin/esphome logs purifier-b.yaml --device <ip>
```

## Recovery

If the board can't join Wi-Fi for 90 s, it opens a hotspot named
`Purifier-B Fallback` (password: `fallback_ap_password` in `secrets.yaml`).
Join it from a phone; the captive portal at 192.168.4.1 lets you enter new
Wi-Fi credentials or upload a firmware `.bin`.
