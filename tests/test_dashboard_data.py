# risk: high
"""Phase 4 Task 4.1 contract 1-8: dashboard JSON data endpoints, static assets, security headers (local DB, skipped when unreachable)."""
import dataclasses
import importlib.resources
import os
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config, load_dotenv
from lutetia.db import Database
from lutetia.models import Device, GpsPosition, Telemetry
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
        await conn.execute("DELETE FROM gps_position WHERE device_id = $1", dev)
        await conn.execute("DELETE FROM device WHERE device_id = $1", dev)


def _ms(dt):
    return int(dt.timestamp() * 1000)


def _gps(dev, dt):
    ms = _ms(dt)
    return GpsPosition(dev, ms, ms, ms, 22.5, 114.0, 10000.0, 0, 0.0, 0.0, 0, 0,
                       None, None, 1, None, None, None, None, "poll", {})


async def test_data_overview_requires_session_json(db):
    async with TestClient(TestServer(make_app(db))) as client:
        r = await client.get("/dashboard/data/overview", allow_redirects=False)
        assert r.status == 401
        assert "error" in await r.json()
        await login(client)
        r = await client.get("/dashboard/data/overview", allow_redirects=False)
        assert r.status == 200
        body = await r.json()
        for k in ("generated_at", "devices", "latest_sensor", "latest_gps", "receiver", "api_calls_24h", "anomalies"):
            assert k in body, k


async def test_data_overview_marks_stale(db):
    dev = "test-dash-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("dingtek", dev, "dash-stale", "DC414", True, {})])
    try:
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            body = await (await client.get("/dashboard/data/overview")).json()
            rows = [d for d in body["devices"] if d["device_id"] == dev]
            assert len(rows) == 1
            assert rows[0]["stale"] is True
    finally:
        await cleanup(db, dev)


async def test_data_telemetry_7d_raw_and_30d_hourly(db):
    dev = "test-dash-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("dingtek", dev, "dash-tel", "DC414", True, {})])
    # 上一个整点小时内的三个点：必在过去且同一小时
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
    try:
        await db.insert_telemetry([Telemetry(dev, "volt", _ms(base + timedelta(minutes=i + 1)), v, None, "rest")
                                   for i, v in enumerate((3000.0, 3300.0, 3600.0))])
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/data/telemetry", params={"device_id": dev, "keys": "volt", "days": "7"})
            assert r.status == 200
            b7 = await r.json()
            pts7 = b7["series"]["volt"]
            assert len(pts7) == 3
            r = await client.get("/dashboard/data/telemetry", params={"device_id": dev, "keys": "volt", "days": "30"})
            assert r.status == 200
            b30 = await r.json()
            assert b30["hourly"] is True
            pts30 = b30["series"]["volt"]
            assert len(pts30) == 1
            mean = sum(p[1] for p in pts7) / 3.0
            assert pts30[0][1] == pytest.approx(mean, rel=1e-6)
            # 非法入参
            r = await client.get("/dashboard/data/telemetry", params={"device_id": dev, "days": "10"})
            assert r.status == 400
            r = await client.get("/dashboard/data/telemetry", params={"days": "7"})
            assert r.status == 400
            r = await client.get("/dashboard/data/telemetry", params={"device_id": dev, "keys": "volt;drop", "days": "7"})
            assert r.status == 400
    finally:
        await cleanup(db, dev)


async def test_data_positions_recent(db):
    dev = "test-dash-" + str(uuidlib.uuid4())
    now = datetime.now(timezone.utc)
    try:
        await db.insert_gps_positions([_gps(dev, now - timedelta(hours=2)),
                                       _gps(dev, now - timedelta(hours=1)),
                                       _gps(dev, now - timedelta(days=40))])
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/data/positions", params={"device_id": dev, "days": "7"})
            assert r.status == 200
            pos = (await r.json())["positions"]
            assert len(pos) == 2
            t = [datetime.fromisoformat(p["update_time"].replace("Z", "+00:00")) for p in pos]
            assert t[0] > t[1]  # 倒序
    finally:
        await cleanup(db, dev)


async def test_static_served_without_session(db):
    async with TestClient(TestServer(make_app(db))) as client:
        r = await client.get("/static/vendor/chart.umd.js", allow_redirects=False)
        assert r.status == 200
        assert "javascript" in r.headers["Content-Type"]
        for path in ("/static/..%2Fpyproject.toml", "/static/../pyproject.toml", "/static/%2e%2e/pyproject.toml"):
            r = await client.get(path, allow_redirects=False)
            assert r.status != 200, path
            assert "[project]" not in await r.text(), path


async def test_security_headers_on_pages(db):
    async with TestClient(TestServer(make_app(db))) as client:
        r = await client.get("/login")
        assert "script-src 'self'" in r.headers.get("Content-Security-Policy", "")
        assert r.headers.get("X-Content-Type-Options", "").lower() == "nosniff"
        assert r.headers.get("X-Frame-Options", "").upper() == "DENY"


async def test_overview_page_has_viewport_and_no_meta_refresh(db):
    async with TestClient(TestServer(make_app(db))) as client:
        await login(client)
        r = await client.get("/dashboard/", allow_redirects=False)
        assert r.status == 200
        html = await r.text()
        assert 'name="viewport"' in html
        assert "/static/app.js" in html
        assert 'id="tbl-devices"' in html
        assert 'http-equiv="refresh"' not in html.lower()


def test_static_is_package_data():
    assert importlib.resources.files("lutetia").joinpath("web/static/vendor/chart.umd.js").is_file()


# ---- Task 4.1 审查修复：W41-1 ~ W41-4 红锁 ----
BEARER = {"Authorization": "Bearer k-test"}


async def test_nul_in_device_id_is_400_with_security_headers(db):
    # risk: high  (H-1: device_id 含 NUL 不能 500 且无安全头)
    async with TestClient(TestServer(make_app(db))) as client:
        await login(client)
        for path, hdr in (("/dashboard/data/telemetry?days=7&device_id=%00abc", {}),
                          ("/dashboard/data/positions?days=7&device_id=%00abc", {}),
                          ("/api/v1/positions?device_id=%00abc", BEARER),
                          ("/api/v1/telemetry?device_id=%00abc", BEARER)):
            r = await client.get(path, headers=hdr, allow_redirects=False)
            assert r.status == 400, path
            assert "json" in r.headers.get("Content-Type", ""), path
            assert "Content-Security-Policy" in r.headers, path


async def test_unhandled_error_is_500_json_with_headers(db, monkeypatch):
    # risk: high  (H-1: 未捕获异常兜底成 JSON 500 且仍带安全头)
    async def boom(self, *a, **kw):
        raise RuntimeError("boom")
    monkeypatch.setattr(Database, "telemetry_series", boom, raising=False)
    async with TestClient(TestServer(make_app(db))) as client:
        await login(client)
        r = await client.get("/dashboard/data/telemetry", params={"device_id": "x", "days": "7"})
        assert r.status == 500
        assert await r.json() == {"error": "internal error"}
        assert "Content-Security-Policy" in r.headers
        assert r.headers.get("X-Content-Type-Options", "").lower() == "nosniff"


async def test_keys_are_deduplicated(db):
    # risk: medium  (M-1)
    dev = "test-dash-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("dingtek", dev, "dash-dup", "DC414", True, {})])
    base = datetime.now(timezone.utc) - timedelta(hours=2)
    try:
        await db.insert_telemetry([Telemetry(dev, "volt", _ms(base + timedelta(minutes=i)), 3000.0 + i, None, "rest")
                                   for i in range(3)])
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/data/telemetry",
                                 params={"device_id": dev, "keys": "volt,volt,volt", "days": "7"})
            assert r.status == 200
            series = (await r.json())["series"]
            assert list(series.keys()) == ["volt"]
            assert len(series["volt"]) == 3
    finally:
        await cleanup(db, dev)


async def test_truncation_keeps_newest_points(db):
    # risk: high  (Q-1: 超 1500 点丢最旧的，不丢最新的)
    dev = "test-dash-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("dingtek", dev, "dash-trunc", "DC414", True, {})])
    base = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=1700)
    try:
        await db.insert_telemetry([Telemetry(dev, "volt", _ms(base + timedelta(minutes=i)), 3000.0 + i, None, "rest")
                                   for i in range(1600)])
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            r = await client.get("/dashboard/data/telemetry", params={"device_id": dev, "keys": "volt", "days": "7"})
            assert r.status == 200
            body = await r.json()
            pts = body["series"]["volt"]
            assert len(pts) == 1500
            assert body["truncated"] is True
            ts = [datetime.fromisoformat(p[0].replace("Z", "+00:00")) for p in pts]
            assert ts == sorted(ts)
            assert ts[0] > base + timedelta(minutes=99)  # 最旧 100 条被丢
            assert ts[-1] == base + timedelta(minutes=1599)  # 最新一条保留
    finally:
        await cleanup(db, dev)


async def test_cards_layout_markup_and_css(db):
    # risk: medium  (M-2: 窄屏卡片排版的标记与样式)
    async with TestClient(TestServer(make_app(db))) as client:
        await login(client)
        html = await (await client.get("/dashboard/")).text()
        assert 'class="cards"' in html
        assert "data-label=" in html
        r = await client.get("/static/app.css")
        assert r.status == 200
        css = await r.text()
        assert "attr(data-label)" in css
        assert "max-width: 600px" in css
