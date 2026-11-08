"""Integration tests against a real PostgreSQL (DATABASE_URL); skipped when it is unreachable."""
import dataclasses
import os
import uuid as uuidlib

import pytest

from lutetia.config import load_dotenv
from lutetia.db import Database, DatabaseConnectError, is_transient_db_error
from lutetia.models import Device
from lutetia.parsers.dingtek import parse_attributes, parse_timeseries
from lutetia.parsers.gps51 import parse_lastposition, parse_push_payload

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")


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


async def test_gps_insert_is_idempotent(db, gps51_lastposition):
    dev = "test-db-" + str(uuidlib.uuid4())
    rows = [dataclasses.replace(p, device_id=dev) for p in parse_lastposition(gps51_lastposition)]
    await db.upsert_devices([Device("gps51", dev, "test", "t", None, {})])
    try:
        first = await db.insert_gps_positions(rows)
        second = await db.insert_gps_positions(rows)
        assert first == len(rows)
        assert second == 0
        # a push for the same (deviceid, updatetime) is also a no-op
        p = rows[0]
        pushed = parse_push_payload({"deviceid": dev, "lat": 1, "lon": 2, "updatetime": p.update_time})
        assert await db.insert_gps_positions(pushed) == 0
    finally:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM gps_position WHERE device_id = $1", dev)
            await conn.execute("DELETE FROM device WHERE device_id = $1", dev)


async def test_telemetry_insert_is_idempotent(db, dingtek_history):
    dev = "test-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("dingtek", dev, "test", "DC414", None, {})])
    rows = parse_timeseries(dev, dingtek_history, origin="rest")
    assert await db.insert_telemetry(rows) == len(rows)
    assert await db.insert_telemetry(rows) == 0
    async with db.pool.acquire() as conn:
        n = await conn.fetchval("SELECT count(*) FROM sensor_telemetry WHERE device_id = $1", dev)
        volt = await conn.fetchval(
            "SELECT value_si FROM sensor_telemetry_v WHERE device_id = $1 AND key = 'volt' ORDER BY ts DESC LIMIT 1", dev)
        await conn.execute("DELETE FROM sensor_telemetry WHERE device_id = $1", dev)
        await conn.execute("DELETE FROM device WHERE device_id = $1", dev)
    assert n == len(rows)
    assert volt == pytest.approx(3.60)


async def test_attributes_and_status(db, dingtek_summary):
    real = "79702a70-9ba1-11f1-898a-012e63463e84"
    uuid = "test-db-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("dingtek", uuid, "test", "DC414", None, {})])
    try:
        attrs = parse_attributes(uuid, dingtek_summary[real]["attrs"])
        await db.upsert_attributes(attrs)
        await db.upsert_attributes(attrs)
        await db.set_expected_online("dingtek", uuid, True)
        status = {(r["source"], r["device_id"]): r for r in await db.device_status()}
        assert status[("dingtek", uuid)]["expected_online"] is True
    finally:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM sensor_attribute WHERE device_id = $1", uuid)
            await conn.execute("DELETE FROM device WHERE device_id = $1", uuid)


async def test_api_call_counter(db):
    from datetime import datetime, timedelta, timezone
    before = await db.api_calls_since("test", datetime.now(timezone.utc) - timedelta(minutes=1))
    await db.record_api_call("test", "ping", True)
    after = await db.api_calls_since("test", datetime.now(timezone.utc) - timedelta(minutes=1))
    assert after == before + 1
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM api_call WHERE source = 'test'")


def test_database_connect_error_is_not_transient_and_hides_host():
    e = DatabaseConnectError("InvalidPasswordError")
    assert isinstance(e, OSError)  # 仍是 OSError，但显式排除出可重试
    assert is_transient_db_error(e) is False
    assert str(e) == "database connect failed: InvalidPasswordError"
    assert is_transient_db_error(ConnectionResetError()) is True
