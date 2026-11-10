"""Purifier fan target: recent PM2.5 -> fan duty percent (CLAUDE.md 6.3).

Goal is PM2.5 < 1 ug/m3 in an occupied room, so the curve never drops below
a quiet floor and ramps up gradually rather than jumping to 100%. "Off" is a
manual action and never comes from here.

A boost, POSTed by Home Assistant when a cat uses the Litter-Robot, raises the
duty until it expires. Litter smell is gas, which the PM sensor can't see, so
the curve alone never reacts to it.
"""
import math
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

# (PM2.5 ug/m3, duty %) points, ascending. Duty holds at the first point's
# value below it (the quiet floor) and at the last point's value above it.
CURVE = ((0.5, 25), (1.0, 40), (2.0, 60), (5.0, 85), (10.0, 100))

# Duty when there is no recent PM data to act on.
FALLBACK_PCT = int(os.environ.get("AIRMON_PURIFIER_FALLBACK_PCT", "40"))

# PM2.5 is averaged over this trailing window.
WINDOW_MINUTES = 5

PURIFIERS = frozenset({"a", "b"})

# Boost duty, and a quieter one from NIGHT_START to NIGHT_END local time,
# since purifier B shares the bedroom with the Litter-Robot.
BOOST_PCT = 100
NIGHT_BOOST_PCT = 70
NIGHT_START = time(23, 0)
NIGHT_END = time(7, 0)
LOCAL_TZ = ZoneInfo("America/New_York")

# Longest boost one request can set.
MAX_BOOST_MINUTES = 60

# Boost expiry per purifier. Kept in memory: uvicorn runs a single worker, and
# a boost lost to a restart just leaves the curve in charge.
_boost_until: dict[str, datetime] = {}


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


def set_boost(name: str, minutes: int, now: datetime) -> datetime | None:
    """Boost `name` until `minutes` from now, replacing any current boost.

    0 clears it. Returns the new expiry.
    """
    if minutes == 0:
        _boost_until.pop(name, None)
        return None
    until = now + timedelta(minutes=minutes)
    _boost_until[name] = until
    return until


def boost_until(name: str, now: datetime) -> datetime | None:
    """Expiry of `name`'s boost, or None if none is running."""
    until = _boost_until.get(name)
    return until if until is not None and until > now else None


def boost_pct(now: datetime) -> int:
    """BOOST_PCT, or NIGHT_BOOST_PCT from NIGHT_START to NIGHT_END local."""
    t = now.astimezone(LOCAL_TZ).time()
    # The night window wraps midnight.
    return NIGHT_BOOST_PCT if t >= NIGHT_START or t < NIGHT_END else BOOST_PCT


def target(pm25_avg: float | None, boosted: bool, now: datetime) -> tuple[int, str]:
    """Duty percent and its reason: "curve", "stale" or "boost".

    A boost raises the duty to boost_pct(now) but never lowers it, so a PM
    spike at night can still take the fans past the night boost.
    """
    duty = target_pct(pm25_avg)
    if boosted and (boost := boost_pct(now)) >= duty:
        return boost, "boost"
    return duty, "curve" if pm25_avg is not None else "stale"
