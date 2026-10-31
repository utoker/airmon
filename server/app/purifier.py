"""Purifier fan target: recent PM2.5 -> fan duty percent (CLAUDE.md 6.3).

Goal is PM2.5 < 1 ug/m3 in an occupied room, so the curve never drops below
a quiet floor and ramps up gradually rather than jumping to 100%. "Off" is a
manual action and never comes from here.
"""
import math
import os

# (PM2.5 ug/m3, duty %) points, ascending. Duty holds at the first point's
# value below it (the quiet floor) and at the last point's value above it.
CURVE = ((0.5, 25), (1.0, 40), (2.0, 60), (5.0, 85), (10.0, 100))

# Duty when there is no recent PM data to act on.
FALLBACK_PCT = int(os.environ.get("AIRMON_PURIFIER_FALLBACK_PCT", "40"))

# PM2.5 is averaged over this trailing window.
WINDOW_MINUTES = 5

PURIFIERS = frozenset({"a", "b"})


def target_pct(pm25_avg: float | None) -> int:
    """Map average PM2.5 to a duty percent, piecewise-linear through CURVE.

    Rounds half up (32.5 -> 33), not Python's round-half-to-even.
    """
    if pm25_avg is None:
        return FALLBACK_PCT
    x0, y0 = CURVE[0]
    if pm25_avg <= x0:
        return y0
    for x1, y1 in CURVE[1:]:
        if pm25_avg <= x1:
            return math.floor(y0 + (y1 - y0) * (pm25_avg - x0) / (x1 - x0) + 0.5)
        x0, y0 = x1, y1
    return y0
