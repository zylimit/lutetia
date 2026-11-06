# risk: high
"""gps_position.raw 必须是 JSON 对象而不是 JSON 字符串(F8)。连不上库则 skip；只写 test-raw-<uuid> 的行并清理。"""
import logging
import os
import uuid as uuidlib
from pathlib import Path

import pytest

from lutetia.config import load_dotenv
from lutetia.db import Database
from lutetia.models import Device, Telemetry
from lutetia.parsers.gps51 import parse_push_payload

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
SQL_002 = Path(__file__).resolve().parents[1] / "lutetia" / "sql" / "002_raw_jsonb_fix.sql"


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


async def test_f8_insert_stores_raw_as_jsonb_object(db):
    # risk: high  (M-1: 双重编码，库里 raw 是字符串，raw->>'deviceid' 查不出来)
    dev = "test-raw-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("gps51", dev, "test", "X", None, {})])
    try:
        rows = parse_push_payload({"deviceid": dev, "lat": 1, "lon": 2, "updatetime": 1793900000000})
        assert len(rows) == 1
        rows[0].raw = {"deviceid": dev, "k": 1}
        assert await db.insert_gps_positions(rows) == 1
        async with db.pool.acquire() as conn:
            t, did = await conn.fetchrow(
                "SELECT jsonb_typeof(raw), raw->>'deviceid' FROM gps_position WHERE device_id = $1", dev)
        assert (t, did) == ("object", dev), "raw 应为 jsonb object；实际 (%s, %s)" % (t, did)
    finally:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM gps_position WHERE device_id = $1", dev)
            await conn.execute("DELETE FROM device WHERE device_id = $1", dev)


async def test_f8_migration_002_converts_string_raw_to_object_and_is_idempotent(db):
    # risk: high  (存量 4 行字符串 raw 靠这个迁移修；事务内跑并回滚，不改真库其它行)
    assert SQL_002.exists(), "缺 lutetia/sql/002_raw_jsonb_fix.sql"
    sql = SQL_002.read_text(encoding="utf-8")
    dev = "test-raw-" + str(uuidlib.uuid4())
    async with db.pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            await conn.execute("INSERT INTO device (source, device_id) VALUES ('gps51', $1)", dev)
            await conn.execute(
                "INSERT INTO gps_position (device_id, update_time, origin, raw) "
                "VALUES ($1, now(), 'push', to_jsonb($2::text))", dev, '{"deviceid": "%s", "k": 1}' % dev)
            assert await conn.fetchval("SELECT jsonb_typeof(raw) FROM gps_position WHERE device_id=$1", dev) == "string"
            await conn.execute(sql)
            await conn.execute(sql)   # 幂等：二次执行不报错、结果不变
            t, did = await conn.fetchrow(
                "SELECT jsonb_typeof(raw), raw->>'deviceid' FROM gps_position WHERE device_id=$1", dev)
            assert (t, did) == ("object", dev)
        finally:
            await tr.rollback()


async def test_f12_poison_gps_row_is_skipped_good_row_stored(db, caplog):
    # risk: high  (N-1: 一条越界毒行不能拖垮整批，否则游标/推送整批丢)
    dev = "test-raw-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("gps51", dev, "test", "X", None, {})])
    good_t, bad_t = 1793900000000, 1793900001000
    try:
        good = parse_push_payload({"deviceid": dev, "lat": 1, "lon": 2, "updatetime": good_t})[0]
        bad = parse_push_payload({"deviceid": dev, "lat": 1, "lon": 2, "updatetime": bad_t})[0]
        bad.moving = 70000      # 超 smallint
        caplog.set_level(logging.WARNING)
        n = await db.insert_gps_positions([good, bad])
        assert n == 1, "毒行应被跳过、正常行入库，返回 1；实际 %s" % n
        async with db.pool.acquire() as conn:
            cnt = await conn.fetchval("SELECT count(*) FROM gps_position WHERE device_id = $1", dev)
        assert cnt == 1
        warns = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(str(bad_t) in m or "2026" in m for m in warns), "应有 warning 带毒行 update_time，实际: %s" % warns
    finally:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM gps_position WHERE device_id = $1", dev)
            await conn.execute("DELETE FROM device WHERE device_id = $1", dev)


async def test_f12_poison_telemetry_row_is_skipped(db):
    # risk: high  (N-1: Dingtek 一个窗口里一条含 NUL 的文本不能让整窗丢)
    dev = "test-raw-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("dingtek", dev, "test", "DC414", None, {})])
    try:
        rows = [Telemetry(dev, "k_ok", 1793900000000, 1.0, None, "rest"),
                Telemetry(dev, "k_bad", 1793900000000, None, "a\u0000b", "rest")]
        n = await db.insert_telemetry(rows)
        assert n == 1, "毒行应被跳过、正常行入库，返回 1；实际 %s" % n
        async with db.pool.acquire() as conn:
            keys = [r[0] for r in await conn.fetch("SELECT key FROM sensor_telemetry WHERE device_id = $1", dev)]
        assert keys == ["k_ok"]
    finally:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM sensor_telemetry WHERE device_id = $1", dev)
            await conn.execute("DELETE FROM device WHERE device_id = $1", dev)
