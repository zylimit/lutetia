# risk: high
"""Phase 4 Task 4.4 contract 1-7: map page + /dashboard/data/map (login gate, shape, tracks/days, bad coords, CSP-safe HTML, home link). Local DB, skipped when unreachable."""
import dataclasses
import os
import re
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config, load_dotenv
from lutetia.db import Database
from lutetia.models import Attribute, Device, GpsPosition, Telemetry
from lutetia.web import WebServer

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
PWD = "pw-test"


@pytest.fixture
async def db():
    if not DB_URL:
        pytest.skip("DATABASE_URL not set")
    d = Database(DB_URL)
    try:
        await d.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip("database unreachable: %s" % e)
    yield d
    await d.close()


def make_cfg(**kw):
    return dataclasses.replace(Config.from_env(), dashboard_pwd=PWD, api_key="k-test",
                               dashboard_host="127.0.0.1", **kw)


def make_app(db):
    return WebServer(make_cfg(), db, None, datetime.now(timezone.utc)).build_app()


async def login(client):
    return await client.post("/login", data={"username": "admin", "password": PWD, "next": ""},
                             allow_redirects=False)


async def cleanup(db, *devs):
    async with db.pool.acquire() as conn:
        for dev in devs:
            await conn.execute("DELETE FROM sensor_telemetry WHERE device_id = $1", dev)
            await conn.execute("DELETE FROM sensor_attribute WHERE device_id = $1", dev)
            await conn.execute("DELETE FROM gps_position WHERE device_id = $1", dev)
            await conn.execute("DELETE FROM device WHERE device_id = $1", dev)


def _ms(dt):
    return int(dt.timestamp() * 1000)


def _gps(dev, dt, lat, lon, dist_m):
    ms = _ms(dt)
    return GpsPosition(dev, ms, ms, ms, lat, lon, 10000.0, 0, 0.0, dist_m, 0, 0,
                       None, None, 1, None, None, None, None, "poll", {})


def _dt_id():
    return "test-dash-" + str(uuidlib.uuid4())


def _gps_id():
    return "test-dash-gps-" + str(uuidlib.uuid4())


async def test_map_page_requires_login(db):
    async with TestClient(TestServer(make_app(db))) as client:
        r = await client.get("/dashboard/map", allow_redirects=False)
        assert r.status == 302
        assert "/login" in r.headers["Location"]
        r = await client.get("/dashboard/data/map", allow_redirects=False)
        assert r.status == 401
        assert "json" in r.headers.get("Content-Type", "")


async def test_map_page_renders(db):
    async with TestClient(TestServer(make_app(db))) as client:
        await login(client)
        r = await client.get("/dashboard/map", allow_redirects=False)
        assert r.status == 200
        html = await r.text()
        for s in ('id="map"', 'id="device-list"', "/static/vendor/leaflet.js", "/static/map.js", "OpenStreetMap"):
            assert s in html, s
        assert 'data-days="0"' in html
        r = await client.get("/dashboard/map", params={"tracks": "1"})
        assert 'data-days="7"' in await r.text()


async def test_map_data_shape(db):
    mh, gp = _dt_id(), _gps_id()
    now = datetime.now(timezone.utc)
    older, newer = now - timedelta(hours=2), now - timedelta(hours=1)
    await db.upsert_devices([Device("dingtek", mh, "map-mh", "DC414", True, {}),
                             Device("gps51", gp, "map-gps", "GPS", True, {})])
    try:
        await db.upsert_attributes([Attribute(mh, "latitude", "48.85", _ms(now)),
                                    Attribute(mh, "longitude", "2.35", _ms(now))])
        await db.insert_telemetry([Telemetry(mh, "volt", _ms(now), 360.0, None, "rest")])
        await db.insert_gps_positions([_gps(gp, older, 22.5011, 114.0011, 1000.0),
                                       _gps(gp, newer, 22.5022, 114.0022, 2000.0)])
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/data/map")
            assert r.status == 200
            j = await r.json()
            assert "generated_at" in j
            m = [x for x in j["manholes"] if x["device_id"] == mh]
            assert len(m) == 1
            assert m[0]["lat"] == pytest.approx(48.85)
            assert m[0]["lon"] == pytest.approx(2.35)
            assert m[0]["volt"] == pytest.approx(3.6)
            g = [x for x in j["gps"] if x["device_id"] == gp]
            assert len(g) == 1
            assert g[0]["lat"] == pytest.approx(22.5022)
            assert g[0]["lon"] == pytest.approx(114.0022)
            assert g[0]["track"] == []
    finally:
        await cleanup(db, mh, gp)


async def test_map_data_tracks_and_days(db):
    gp = _gps_id()
    now = datetime.now(timezone.utc)
    await db.upsert_devices([Device("gps51", gp, "map-gps", "GPS", True, {})])
    try:
        await db.insert_gps_positions([_gps(gp, now - timedelta(hours=2), 22.5011, 114.0011, 1000.0),
                                       _gps(gp, now - timedelta(hours=1), 22.5022, 114.0022, 2000.0)])
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/data/map", params={"days": "7"})
            assert r.status == 200
            g = [x for x in (await r.json())["gps"] if x["device_id"] == gp][0]
            assert len(g["track"]) == 2
            assert g["track"][0][0] == pytest.approx(22.5011)
            assert g["track"][1][0] == pytest.approx(22.5022)
            for bad in ("30", "abc"):
                r = await client.get("/dashboard/data/map", params={"days": bad})
                assert r.status == 400, bad
    finally:
        await cleanup(db, gp)


async def test_map_data_skips_bad_coords(db):
    bad_lat, only_lat = _dt_id(), _dt_id()
    now = datetime.now(timezone.utc)
    await db.upsert_devices([Device("dingtek", bad_lat, "map-badlat", "DC414", True, {}),
                             Device("dingtek", only_lat, "map-onlylat", "DC414", True, {})])
    try:
        await db.upsert_attributes([Attribute(bad_lat, "latitude", "abc", _ms(now)),
                                    Attribute(bad_lat, "longitude", "2.35", _ms(now)),
                                    Attribute(only_lat, "latitude", "48.85", _ms(now))])
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/data/map")
            assert r.status == 200
            ids = {x["device_id"] for x in (await r.json())["manholes"]}
            assert bad_lat not in ids
            assert only_lat not in ids
    finally:
        await cleanup(db, bad_lat, only_lat)


async def test_map_page_has_no_inline_script(db):
    async with TestClient(TestServer(make_app(db))) as client:
        await login(client)
        r = await client.get("/dashboard/map")
        assert r.status == 200
        html = await r.text()
        assert re.search(r"<script(?![^>]*\bsrc=)", html) is None
        assert re.search(r"\bon[a-z]+\s*=", html) is None


async def test_dashboard_links_to_map(db):
    async with TestClient(TestServer(make_app(db))) as client:
        await login(client)
        r = await client.get("/dashboard/")
        assert r.status == 200
        assert 'href="/dashboard/map"' in await r.text()
