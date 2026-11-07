# risk: high
"""Phase 4 Task 4.5: map 7-day track thinned to one point per 5-minute bucket (newest kept), limit keeps newest buckets. Local DB, skipped when unreachable."""
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp.test_utils import TestClient, TestServer

from test_map_page import Device, _gps, _gps_id, cleanup, db, login, make_app  # noqa: F401  (db is a fixture)


def _three_points(gp):
    """A, B same 5-min bucket (B newer), C in another bucket. T0 is bucket-aligned + 10s so A/B never straddle a bucket."""
    base = datetime.now(timezone.utc) - timedelta(hours=2)
    aligned = int(base.timestamp()) // 300 * 300
    t0 = datetime.fromtimestamp(aligned + 10, tz=timezone.utc)
    return [_gps(gp, t0, 22.5011, 114.0011, 1000.0),
            _gps(gp, t0 + timedelta(seconds=60), 22.5022, 114.0022, 2000.0),
            _gps(gp, t0 + timedelta(seconds=3600), 22.5033, 114.0033, 3000.0)]


async def test_map_track_thinned_5min(db):
    gp = _gps_id()
    await db.upsert_devices([Device("gps51", gp, "map-gps", "GPS", True, {})])
    try:
        await db.insert_gps_positions(_three_points(gp))
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/data/map", params={"days": "7"})
            assert r.status == 200
            g = [x for x in (await r.json())["gps"] if x["device_id"] == gp][0]
            assert len(g["track"]) == 2
            assert g["track"][0][0] == pytest.approx(22.5022)
            assert g["track"][1][0] == pytest.approx(22.5033)
    finally:
        await cleanup(db, gp)


# risk: medium
async def test_positions_thinned_limit_keeps_newest(db):
    gp = _gps_id()
    await db.upsert_devices([Device("gps51", gp, "map-gps", "GPS", True, {})])
    try:
        await db.insert_gps_positions(_three_points(gp))
        rows = await db.positions_thinned(gp, 7, 300, 1)
        assert len(rows) == 1
        assert rows[0]["lat"] == pytest.approx(22.5033)
    finally:
        await cleanup(db, gp)
