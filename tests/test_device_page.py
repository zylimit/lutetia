# risk: high
"""Phase 4 Task 4.3 contract 1-7: device detail page (login gate, 404s, dingtek charts, gps map, escaping, links, CSP-safe HTML). Local DB, skipped when unreachable."""
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
    return WebServer(make_cfg(), db, datetime.now(timezone.utc)).build_app()


async def login(client):
    return await client.post("/login", data={"username": "admin", "password": PWD, "next": ""},
                             allow_redirects=False)


async def cleanup(db, dev):
    async with db.pool.acquire() as conn:
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


async def test_device_page_requires_login(db):
    async with TestClient(TestServer(make_app(db))) as client:
        r = await client.get("/dashboard/device/dingtek/whatever", allow_redirects=False)
        assert r.status == 302
        assert "/login" in r.headers["Location"]


async def test_device_page_404s(db):
    async with TestClient(TestServer(make_app(db))) as client:
        await login(client)
        for path in ("/dashboard/device/x/y", "/dashboard/device/dingtek/%00",
                     "/dashboard/device/dingtek/does-not-exist"):
            r = await client.get(path, allow_redirects=False)
            assert r.status == 404, path
            assert "default-src 'self'" in r.headers.get("Content-Security-Policy", ""), path
    # control: an existing device on the same route answers 200, so the 404s above mean "not found", not "route missing"
    dev = _dt_id()
    await db.upsert_devices([Device("dingtek", dev, "dash-404ctl", "DC414", True, {})])
    try:
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/device/dingtek/" + dev, allow_redirects=False)
            assert r.status == 200
    finally:
        await cleanup(db, dev)


async def test_dingtek_page_renders_charts_and_tables(db):
    dev = _dt_id()
    now = datetime.now(timezone.utc)
    await db.upsert_devices([Device("dingtek", dev, "dash-page", "DC414", True, {})])
    try:
        await db.insert_telemetry([Telemetry(dev, "volt", _ms(now - timedelta(minutes=30)), 3333.0, None, "rest"),
                                   Telemetry(dev, "volt", _ms(now - timedelta(minutes=20)), 3444.0, None, "rest")])
        await db.upsert_attributes([Attribute(dev, "uploadInterval", "1", _ms(now))])
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/device/dingtek/" + dev, allow_redirects=False)
            assert r.status == 200
            html = await r.text()
            for s in ('id="chart-volt"', "chart-temperature", "chart-rsrp", "/static/vendor/chart.umd.js",
                      "/static/device.js", 'data-days="7"', "uploadInterval"):
                assert s in html, s
            assert "3333" in html or "3.333" in html
            r = await client.get("/dashboard/device/dingtek/" + dev, params={"days": "30"})
            assert 'data-days="30"' in await r.text()
            r = await client.get("/dashboard/device/dingtek/" + dev, params={"days": "10"})
            assert 'data-days="7"' in await r.text()
    finally:
        await cleanup(db, dev)


async def test_gps_page_renders_map_and_positions(db):
    dev = _gps_id()
    now = datetime.now(timezone.utc)
    await db.upsert_devices([Device("gps51", dev, "dash-gps", "GPS", True, {})])
    try:
        await db.insert_gps_positions([_gps(dev, now - timedelta(hours=2), 22.5011, 114.0011, 7777000.0),
                                       _gps(dev, now - timedelta(hours=1), 22.5022, 114.0022, 7777000.0)])
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/device/gps51/" + dev, allow_redirects=False)
            assert r.status == 200
            html = await r.text()
            for s in ('id="map"', "/static/vendor/leaflet.js", "/static/vendor/leaflet.css",
                      "/static/device.js", "© Google", "里程表 7777.0 km"):
                assert s in html, s
            tail = html.split("最近位置", 1)[1]
            assert "22.5011" in tail and "22.5022" in tail
            assert tail.count("22.50") == 2 or tail.count("22.5011") == 1
    finally:
        await cleanup(db, dev)


async def test_device_page_escapes_name(db):
    dev = _dt_id()
    await db.upsert_devices([Device("dingtek", dev, "<script>alert(1)</script>", "DC414", True, {})])
    try:
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/device/dingtek/" + dev)
            assert r.status == 200
            html = await r.text()
            assert "<script>alert(1)" not in html
            assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    finally:
        await cleanup(db, dev)


async def test_overview_links_to_device_pages(db):
    dev = _dt_id()
    await db.upsert_devices([Device("dingtek", dev, "dash-link", "DC414", True, {})])
    try:
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/", allow_redirects=False)
            assert r.status == 200
            assert 'href="/dashboard/device/dingtek/%s"' % dev in await r.text()
    finally:
        await cleanup(db, dev)


async def test_device_page_has_no_inline_script(db):
    dd, gd = _dt_id(), _gps_id()
    await db.upsert_devices([Device("dingtek", dd, "dash-inl", "DC414", True, {}),
                             Device("gps51", gd, "dash-inl-gps", "GPS", True, {})])
    try:
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            for url in ("/dashboard/device/dingtek/" + dd, "/dashboard/device/gps51/" + gd):
                r = await client.get(url)
                assert r.status == 200, url
                html = await r.text()
                assert not re.search(r"<script(?![^>]*\bsrc=)", html), url
                assert not re.search(r"\bon[a-z]+\s*=", html), url
    finally:
        await cleanup(db, dd)
        await cleanup(db, gd)
