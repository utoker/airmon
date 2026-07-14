#!/usr/bin/env python3
"""One-shot sensor verification. Reads each sensor once and prints raw values."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from drivers import gy21, mhz19b, sps30

MHZ19B_DEVICE = os.environ.get("AIRMON_MHZ19B_DEVICE", "/dev/ttyAMA0")
SPS30_DEVICE  = os.environ.get("AIRMON_SPS30_DEVICE",  "/dev/ttyAMA3")
I2C_BUS       = int(os.environ.get("AIRMON_I2C_BUS", "1"))

OK   = "\033[32mOK\033[0m"
FAIL = "\033[31mFAIL\033[0m"

results: list[tuple[str, bool, str]] = []


def check_gy21() -> None:
    print(f"\n[GY-21] i2c bus {I2C_BUS}, addr 0x40")
    try:
        gy21.soft_reset(I2C_BUS)
        t  = gy21.read_temperature_c(I2C_BUS)
        rh = gy21.read_humidity_pct(I2C_BUS)
        print(f"  temperature: {t:6.2f} degC")
        print(f"  humidity:    {rh:6.2f} %RH")
        if not (-20 <= t <= 60):
            raise RuntimeError(f"temperature {t:.2f} outside plausible indoor range")
        if not (0 <= rh <= 100):
            raise RuntimeError(f"humidity {rh:.2f} outside 0..100")
        results.append(("GY-21", True, f"{t:.2f} degC / {rh:.2f} %RH"))
    except Exception as e:
        print(f"  {FAIL}: {type(e).__name__}: {e}")
        results.append(("GY-21", False, f"{type(e).__name__}: {e}"))


def check_mhz19b() -> None:
    print(f"\n[MH-Z19B] {MHZ19B_DEVICE}, 9600 baud")
    print("  note: needs ~3 min warmup after power-on; early readings may be low/unstable")
    try:
        ppm = mhz19b.read_co2_ppm(MHZ19B_DEVICE)
        print(f"  CO2: {ppm} ppm")
        note = ""
        if ppm < 380 or ppm > 2000:
            note = " (likely warmup or unusual environment)"
        results.append(("MH-Z19B", True, f"{ppm} ppm{note}"))
    except Exception as e:
        print(f"  {FAIL}: {type(e).__name__}: {e}")
        results.append(("MH-Z19B", False, f"{type(e).__name__}: {e}"))


def check_sps30() -> None:
    print(f"\n[SPS30] {SPS30_DEVICE}, 115200 baud, SHDLC")
    try:
        with sps30.SPS30(SPS30_DEVICE) as dev:
            dev.start()
            print("  started measurement, waiting 3 s for first sample...")
            time.sleep(3.0)
            data = dev.read()
            dev.stop()
        for k, v in data.items():
            print(f"  {k:20s} {v:10.3f}")
        results.append(("SPS30", True, f"PM2.5={data['pm2_5_ug_m3']:.2f} ug/m3"))
    except Exception as e:
        print(f"  {FAIL}: {type(e).__name__}: {e}")
        results.append(("SPS30", False, f"{type(e).__name__}: {e}"))


def main() -> int:
    print("airmon sensor verification")
    print(f"  MHZ19B_DEVICE = {MHZ19B_DEVICE}")
    print(f"  SPS30_DEVICE  = {SPS30_DEVICE}")
    print(f"  I2C_BUS       = {I2C_BUS}")

    check_gy21()
    check_mhz19b()
    check_sps30()

    print("\n=== summary ===")
    all_ok = True
    for name, ok, detail in results:
        mark = OK if ok else FAIL
        print(f"  {mark:14s} {name:8s} {detail}")
        if not ok:
            all_ok = False
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
