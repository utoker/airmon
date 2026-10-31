import pytest

from app.purifier import CURVE, FALLBACK_PCT, target_pct


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
