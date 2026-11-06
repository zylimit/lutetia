# risk: high
"""Task 2.5 contract 14-17: read-only query API (Bearer key) via aiohttp TestServer against the local DB."""
import dataclasses
import os
import time
import uuid as uuidlib
from datetime import datetime, timezone

import pytest
from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config, load_dotenv
from lutetia.db import Database
from lutetia.models import Device, GpsPosition, Telemetry
from lutetia.web import WebServer

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
KEY = "k-test"
AUTH = {"Authorization": "Bearer " + KEY}


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


def make_cfg():
    return dataclasses.replace(Config.from_env(), api_key=KEY, dashboard_pwd="pw-test",
                               dashboard_host="127.0.0.1")


def make_app(db):
    return WebServer(make_cfg(), db, None, datetime.now(timezone.utc)).build_app()


async def cleanup(db, dev):
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM sensor_telemetry WHERE device_id = $1", dev)
        await conn.execute("DELETE FROM gps_position WHERE device_id = $1", dev)
        await conn.execute("DELETE FROM device WHERE device_id = $1", dev)


def gps(dev, ts_ms):
    return GpsPosition(dev, ts_ms, ts_ms, ts_ms, 22.5, 114.0, 10000.0, 0, 0.0, 0.0, 0, 0,
                       None, None, 1, None, None, None, None, "poll", {})


async def test_api_requires_bearer_key(db):
    async with TestClient(TestServer(make_app(db))) as client:
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "Basic " + KEY}):
            r = await client.get("/api/v1/devices", headers=headers, allow_redirects=False)
            assert r.status == 401, headers
            assert r.headers.get("WWW-Authenticate") == "Bearer"


async def test_api_four_endpoints_with_key(db):
    dev = "test-api-" + str(uuidlib.uuid4())
    now_ms = int(time.time() * 1000)
    t_old, t_new = now_ms - 120000, now_ms - 60000
    await db.upsert_devices([Device("dingtek", dev, "api-test", "DC414", True, {})])
    try:
        await db.insert_gps_positions([gps(dev, t_old), gps(dev, t_new)])
        await db.insert_telemetry([Telemetry(dev, "volt", t_old, 3600.0, None, "rest"),
                                   Telemetry(dev, "volt", t_new, 3700.0, None, "rest")])
        async with TestClient(TestServer(make_app(db))) as client:
            r = await client.get("/api/v1/devices", headers=AUTH)
            assert r.status == 200
            body = await r.json()
            assert any(d["device_id"] == dev for d in body["devices"])

            r = await client.get("/api/v1/positions", params={"device_id": dev}, headers=AUTH)
            assert r.status == 200
            body = await r.json()
            assert body["count"] == len(body["positions"]) == 2
            rows = body["positions"]
            assert "speed_kmh" in rows[0] and "speed_raw" in rows[0]
            times = [x["update_time"] for x in rows]
            assert times == sorted(times, reverse=True) and times[0] != times[1]

            r = await client.get("/api/v1/telemetry", params={"device_id": dev, "key": "volt"}, headers=AUTH)
            assert r.status == 200
            body = await r.json()
            assert body["count"] == len(body["telemetry"]) == 2
            assert all("value_si" in x for x in body["telemetry"])

            r = await client.get("/api/v1/status", headers=AUTH)
            assert r.status == 200
            body = await r.json()
            assert "started_at" in body and "api_calls_24h" in body
    finally:
        await cleanup(db, dev)


async def test_api_param_validation(db):
    now_ms = int(time.time() * 1000)
    async with TestClient(TestServer(make_app(db))) as client:
        async def get(**params):
            return (await client.get("/api/v1/positions", params=params, headers=AUTH)).status

        assert await get(device_id="x", limit="20000") == 400
        assert await get(device_id="x", limit="0") == 400
        assert await get() == 400
        assert await get(device_id="x", since="notatime") == 400
        assert await get(device_id="x", since=str(now_ms - 3600000)) == 200
        assert await get(device_id="x", since="2026-01-01T00:00:00Z") == 200


async def test_api_has_no_mutating_routes(db):
    app = make_app(db)
    api_methods = []
    for route in app.router.routes():
        res = getattr(route, "resource", None)
        path = (getattr(res, "canonical", None) or "") if res is not None else ""
        if path.startswith("/api/"):
            api_methods.append(route.method)
    assert len(api_methods) >= 4
    for m in api_methods:
        assert m in ("GET", "HEAD"), m
        assert m not in ("POST", "PUT", "DELETE", "PATCH", "*")


# ---- 审查修复：W5 / W6 红锁 + A2 加固 ----
import asyncio  # noqa: E402

FIELDS9 = {"received", "stored", "rejected", "unrecognised", "alarms", "failed",
           "queued", "silent_sec", "message_silent_sec"}


class StubReceiver:
    received, stored, rejected, unrecognised, alarms, failed = 11, 7, 1, 2, 3, 4

    def __init__(self):
        self.queue = asyncio.Queue()
        self.queue.put_nowait(1)

    def silent_for(self):
        return 12.5

    def message_silent_for(self):
        return 30.0


@pytest.mark.parametrize("header,status", [
    ("bearer " + KEY, 200),
    ("BEARER  " + KEY, 200),
    ("Bearer   " + KEY + "  ", 200),
    ("Basic " + KEY, 401),
    ("Bearer wrong", 401),
    ("Bearer", 401),
])
async def test_api_bearer_scheme_case_and_spaces(db, header, status):
    # risk: medium  (W6)
    async with TestClient(TestServer(make_app(db))) as client:
        r = await client.get("/api/v1/devices", headers={"Authorization": header}, allow_redirects=False)
        assert r.status == status, header


def _iso(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


async def test_api_since_until_filter_counts(db):
    # risk: high  (A2: 过滤后的 count，而不是只看 200)
    dev = "test-fix-" + str(uuidlib.uuid4())
    now_ms = int(time.time() * 1000)
    t_old, t_new = now_ms - 3 * 3600 * 1000, now_ms - 3600 * 1000
    mid = now_ms - 2 * 3600 * 1000
    await db.upsert_devices([Device("dingtek", dev, "fix-test", "DC414", True, {})])
    try:
        await db.insert_gps_positions([gps(dev, t_old), gps(dev, t_new)])
        async with TestClient(TestServer(make_app(db))) as client:
            async def count(**params):
                params["device_id"] = dev
                r = await client.get("/api/v1/positions", params=params, headers=AUTH)
                assert r.status == 200
                return (await r.json())["count"]

            assert await count() == 2
            assert await count(since=str(mid)) == 1
            assert await count(until=str(mid)) == 1
            assert await count(since=str(mid), until=str(mid + 1000)) == 0
            assert await count(since=_iso(mid) + "Z") == 1
    finally:
        await cleanup(db, dev)


async def test_api_unencoded_plus_offset_matches_encoded(db):
    # risk: high  (W5: 查询串里未编码的 + 被解成空格，不能 400)
    dev = "test-fix-" + str(uuidlib.uuid4())
    now_ms = int(time.time() * 1000)
    t_old, t_new = now_ms - 3 * 3600 * 1000, now_ms - 3600 * 1000
    mid = now_ms - 2 * 3600 * 1000
    await db.upsert_devices([Device("dingtek", dev, "fix-test", "DC414", True, {})])
    try:
        await db.insert_gps_positions([gps(dev, t_old), gps(dev, t_new)])
        async with TestClient(TestServer(make_app(db))) as client:
            raw = "/api/v1/positions?device_id=%s&since=%s+00:00" % (dev, _iso(mid))
            enc = "/api/v1/positions?device_id=%s&since=%s%%2B00:00" % (dev, _iso(mid))
            r_enc = await client.get(enc, headers=AUTH)
            assert r_enc.status == 200
            r_raw = await client.get(raw, headers=AUTH)
            assert r_raw.status == 200
            assert (await r_raw.json())["count"] == (await r_enc.json())["count"] == 1
    finally:
        await cleanup(db, dev)


async def test_api_telemetry_limit_one(db):
    # risk: medium  (A2)
    dev = "test-fix-" + str(uuidlib.uuid4())
    now_ms = int(time.time() * 1000)
    await db.upsert_devices([Device("dingtek", dev, "fix-test", "DC414", True, {})])
    try:
        await db.insert_telemetry([Telemetry(dev, "volt", now_ms - 120000, 3600.0, None, "rest"),
                                   Telemetry(dev, "volt", now_ms - 60000, 3700.0, None, "rest")])
        async with TestClient(TestServer(make_app(db))) as client:
            r = await client.get("/api/v1/telemetry", params={"device_id": dev, "key": "volt", "limit": "1"},
                                 headers=AUTH)
            assert r.status == 200
            body = await r.json()
            assert body["count"] == len(body["telemetry"]) == 1
    finally:
        await cleanup(db, dev)


async def test_api_status_with_receiver_has_nine_fields(db):
    # risk: medium  (A2)
    app = WebServer(make_cfg(), db, StubReceiver(), datetime.now(timezone.utc)).build_app()
    async with TestClient(TestServer(app)) as client:
        r = await client.get("/api/v1/status", headers=AUTH)
        assert r.status == 200
        rcv = (await r.json())["receiver"]
        assert set(rcv) >= FIELDS9
        assert rcv["received"] == 11 and rcv["queued"] == 1 and rcv["silent_sec"] == 12.5
