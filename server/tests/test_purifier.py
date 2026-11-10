from datetime import datetime, timezone

import pytest

from app.purifier import (
    BOOST_PCT,
    CURVE,
    FALLBACK_PCT,
    LOCAL_TZ,
    NIGHT_BOOST_PCT,
    boost_pct,
    target,
    target_pct,
)


def local(hour, minute=0):
    return datetime(2026, 11, 10, hour, minute, tzinfo=LOCAL_TZ)


@pytest.mark.parametrize("pm25", [0.0, 0.2, 0.5])
def test_floor_at_or_below_first_point(pm25):
    assert target_pct(pm25) == 25


@pytest.mark.parametrize("pm25,expected", CURVE)
def test_each_curve_point(pm25, expected):
    assert target_pct(pm25) == expected


@pytest.mark.parametrize(
    "pm25,expected",
    [
        (0.75, 33),  # 32.5 rounds half up
        (1.5, 50),
        (3.5, 73),  # 72.5
        (7.5, 93),  # 92.5
    ],
)
def test_segment_midpoints(pm25, expected):
    assert target_pct(pm25) == expected


@pytest.mark.parametrize("pm25", [10.0, 12.0, 500.0])
def test_clamps_at_100(pm25):
    assert target_pct(pm25) == 100


def test_none_returns_fallback():
    assert FALLBACK_PCT == 40
    assert target_pct(None) == FALLBACK_PCT


def test_returns_int():
    assert isinstance(target_pct(0.8), int)


@pytest.mark.parametrize("hour,minute", [(7, 0), (12, 0), (22, 59)])
def test_day_boost(hour, minute):
    assert BOOST_PCT == 100
    assert boost_pct(local(hour, minute)) == BOOST_PCT


@pytest.mark.parametrize("hour,minute", [(23, 0), (2, 0), (6, 59)])
def test_night_boost(hour, minute):
    assert NIGHT_BOOST_PCT == 70
    assert boost_pct(local(hour, minute)) == NIGHT_BOOST_PCT


def test_boost_pct_uses_local_time():
    # 04:00 UTC is 23:00 EST.
    assert boost_pct(datetime(2026, 11, 11, 4, 0, tzinfo=timezone.utc)) == NIGHT_BOOST_PCT


def test_target_without_boost():
    assert target(2.0, False, local(12)) == (60, "curve")
    assert target(None, False, local(12)) == (FALLBACK_PCT, "stale")


def test_boost_raises_duty():
    assert target(0.3, True, local(12)) == (100, "boost")
    assert target(None, True, local(2)) == (70, "boost")


def test_boost_never_lowers_duty():
    # The curve's 100% beats the 70% night boost.
    assert target(10.0, True, local(2)) == (100, "curve")
