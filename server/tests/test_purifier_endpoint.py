import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import purifier
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIRMON_DB_PATH", str(tmp_path / "server.db"))
    # Boosts live in module state, so don't let one leak between tests.
    purifier._boost_until.clear()
    with TestClient(app) as c:
        yield c


def post(client, *readings):
    """POST readings given as (minutes_ago, pm25) pairs."""
    now = datetime.now(timezone.utc)
    body = {
        "readings": [
            {
                "id": str(uuid.uuid4()),
                "captured_at": (now - timedelta(minutes=ago)).isoformat().replace("+00:00", "Z"),
                "pm25": pm25,
            }
            for ago, pm25 in readings
        ]
    }
    assert client.post("/api/readings", json=body).status_code == 200


def test_curve_from_recent_window(client):
    # 1.0 and 3.0 inside the window average to 2.0 -> 60%. The 50.0 from
    # 10 minutes ago is outside it, and the row with no PM2.5 isn't counted.
    post(client, (1, 1.0), (3, 3.0), (10, 50.0), (2, None))
    for name in ("a", "b"):
        r = client.get(f"/api/purifier/{name}/target")
        assert r.status_code == 200
        body = r.json()
        assert body["purifier"] == name
        assert body["duty_pct"] == 60
        assert body["pm25_avg"] == pytest.approx(2.0)
        assert body["n"] == 2
        assert body["window_minutes"] == 5
        assert body["reason"] == "curve"
        assert body["boost_until"] is None
        assert datetime.fromisoformat(body["computed_at"]).tzinfo is not None


def test_stale_when_window_empty(client):
    post(client, (10, 0.3))
    body = client.get("/api/purifier/b/target").json()
    assert body["duty_pct"] == 40
    assert body["pm25_avg"] is None
    assert body["n"] == 0
    assert body["reason"] == "stale"


def test_stale_on_empty_db(client):
    body = client.get("/api/purifier/a/target").json()
    assert body["reason"] == "stale"
    assert body["duty_pct"] == 40


def test_unknown_purifier_404(client):
    assert client.get("/api/purifier/c/target").status_code == 404


def boost(client, name, minutes):
    return client.post(f"/api/purifier/{name}/boost", json={"minutes": minutes})


def test_boost_raises_target(client):
    post(client, (1, 0.3))  # curve floor, 25%
    r = boost(client, "b", 10)
    assert r.status_code == 200
    until = datetime.fromisoformat(r.json()["boost_until"])
    left = until - datetime.now(timezone.utc)
    assert timedelta(minutes=9) < left <= timedelta(minutes=10)

    body = client.get("/api/purifier/b/target").json()
    assert body["reason"] == "boost"
    # Which one depends on the time of day the test runs.
    assert body["duty_pct"] in (purifier.BOOST_PCT, purifier.NIGHT_BOOST_PCT)
    assert body["boost_until"] == r.json()["boost_until"]

    # Only the purifier that was boosted.
    a = client.get("/api/purifier/a/target").json()
    assert a["reason"] == "curve"
    assert a["boost_until"] is None


def test_boost_while_stale(client):
    boost(client, "b", 10)
    body = client.get("/api/purifier/b/target").json()
    assert body["reason"] == "boost"
    assert body["pm25_avg"] is None


def test_boost_replaces_rather_than_extends(client):
    first = datetime.fromisoformat(boost(client, "b", 30).json()["boost_until"])
    second = datetime.fromisoformat(boost(client, "b", 10).json()["boost_until"])
    assert second < first


def test_boost_zero_clears(client):
    boost(client, "b", 10)
    assert boost(client, "b", 0).json()["boost_until"] is None
    body = client.get("/api/purifier/b/target").json()
    assert body["reason"] == "stale"
    assert body["boost_until"] is None


def test_expired_boost_is_ignored(client):
    purifier._boost_until["b"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    body = client.get("/api/purifier/b/target").json()
    assert body["reason"] == "stale"
    assert body["boost_until"] is None


@pytest.mark.parametrize("minutes", [-1, 61, "soon"])
def test_boost_out_of_range_422(client, minutes):
    assert boost(client, "b", minutes).status_code == 422


def test_boost_unknown_purifier_404(client):
    assert boost(client, "c", 10).status_code == 404
