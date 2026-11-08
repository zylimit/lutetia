# risk: high
"""Phase 7 Task 7.2: collector heartbeat write (30 s upsert, failure never raises) and the web side reading it (90 s stale rule)."""
import asyncio
import dataclasses
import importlib.metadata
import os
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp.test_utils import TestClient, TestServer

import lutetia
from lutetia import heartbeat
from lutetia.config import Config, load_dotenv
from lutetia.db import Database
from lutetia.models import Device, GpsPosition
from lutetia.web import WebServer, anomalies
from lutetia.web.data import heartbeat_view

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
PWD = "pw-test"
KEY = "k-test"
NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


def beat(age, details=None, **kw):
    row = {"updated_at": NOW - timedelta(seconds=age), "age_sec": float(age), "version": "9.9", "push_last_at": None, "push_count_24h": 3,
           "ws_connected": True, "polling": False,
           "details": details if details is not None else {"received": 5, "silent_sec": 10.0, "message_silent_sec": 20.0}}
    row.update(kw)
    return row


def collector_items(row):
    receiver, collector = heartbeat_view(row)
    items = anomalies.compute(NOW, [], [], [], receiver, [], 1400, 3.4, collector=collector)
    return [i for i in items if i["kind"] == "collector"], items


# ---- pure rules ----
def test_heartbeat_60s_old_is_not_red():
    got, items = collector_items(beat(60))
    assert got == [] and items == []


def test_heartbeat_91s_old_is_red_with_chinese_text():
    got, _ = collector_items(beat(91))
    assert len(got) == 1 and got[0]["level"] == anomalies.LEVEL_RED
    assert got[0]["detail"] == "采集心跳已 1 分 31 秒未更新（阈值 90 秒）"


def test_heartbeat_exactly_90s_is_not_red():
    assert collector_items(beat(90))[0] == []


def test_no_heartbeat_row_is_red_never_reported():
    got, _ = collector_items(None)
    assert len(got) == 1 and got[0]["level"] == anomalies.LEVEL_RED and got[0]["detail"] == "采集从未上报心跳"


def test_collector_kind_sorts_first_and_has_label():
    assert anomalies.KIND_ORDER[0] == "collector" and anomalies.KIND_LABELS["collector"] == "采集"
    _, items = collector_items(beat(3000))
    assert items[0]["kind"] == "collector"


def test_silent_seconds_keep_growing_with_heartbeat_age():
    # SV-1: collector died 3000 s ago; written silent_sec was 10 -> shown ~3010, push rule fires alongside the heartbeat rule
    receiver, collector = heartbeat_view(beat(3000))
    assert receiver["silent_sec"] == pytest.approx(3010.0) and receiver["message_silent_sec"] == pytest.approx(3020.0)
    assert collector["stale"] is True and collector["age_sec"] == pytest.approx(3000.0)
    _, items = collector_items(beat(3000))
    assert {i["kind"] for i in items} == {"collector", "push"}


def test_heartbeat_view_no_row_shape():
    receiver, collector = heartbeat_view(None)
    assert receiver is None and collector["updated_at"] is None and collector["stale"] is True
    assert set(collector) == {"updated_at", "age_sec", "stale", "version", "ws_connected", "polling", "push_last_at", "push_count_24h", "collector_started_at"}


def test_stale_threshold_is_single_constant():
    assert anomalies.HEARTBEAT_STALE_SEC == 90 and heartbeat.HEARTBEAT_SEC == 30


def test_version_comes_from_package_metadata():
    # read from installed metadata, not hard-coded (the local editable install may lag pyproject.toml, so no pyproject compare here)
    assert lutetia.__version__ == importlib.metadata.version("lutetia")
    assert lutetia.__version__ != "0.1.0"


def test_collector_line_wording():
    from lutetia.web.dashboard import collector_line
    fresh = heartbeat_view(beat(60))[1]
    assert "最后已知" not in collector_line(fresh) and "WS 已连" in collector_line(fresh) and "巴黎时间" in collector_line(fresh)
    stale = heartbeat_view(beat(91))[1]
    line = collector_line(stale)
    assert line.startswith("采集心跳已过期，最后已知（") and line.index("最后已知") < line.index("WS 已连")
    assert "WS 未启用" in collector_line(heartbeat_view(beat(5, ws_connected=None))[1])
    assert "WS 未连" in collector_line(heartbeat_view(beat(5, ws_connected=False))[1])
    assert collector_line(heartbeat_view(None)[1]) == "采集从未上报心跳"


def test_negative_age_reads_as_zero_not_error():
    receiver, collector = heartbeat_view(beat(0, age_sec=-200.0))
    assert collector["age_sec"] == 0.0 and collector["stale"] is False and receiver["silent_sec"] == pytest.approx(10.0)


# ---- write side ----
class Rcv:
    received, stored, rejected, unrecognised, alarms, failed = 1, 2, 3, 4, 5, 6
    last_position_wall = None

    class queue:
        @staticmethod
        def qsize():
            return 7

    def silent_for(self):
        return 1.5

    def message_silent_for(self):
        return 2.5


class Poller:
    polling = True


class Ws:
    connected = True


class BoomDB:
    async def write_heartbeat(self, *a, **k):
        raise ConnectionError("pg down")


async def test_write_once_failure_is_swallowed_and_reported(caplog):
    assert await heartbeat.write_once(BoomDB(), Rcv(), Poller(), None) is False
    assert any("heartbeat write failed" in r.getMessage() and r.levelname == "WARNING" for r in caplog.records)


@pytest.fixture
async def db():
    if not DB_URL:
        pytest.skip("DATABASE_URL not set")
    d = Database(DB_URL)
    try:
        await d.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip("database unreachable: %s" % e)
    async with d.pool.acquire() as conn:
        await conn.execute("DELETE FROM collector_status")
    yield d
    async with d.pool.acquire() as conn:
        await conn.execute("DELETE FROM collector_status")
    await d.close()


async def test_upsert_twice_keeps_one_row_and_stores_fields(db):
    wall = datetime.now(timezone.utc) - timedelta(minutes=2)
    rcv = Rcv()
    rcv.last_position_wall = wall
    assert await heartbeat.write_once(db, rcv, Poller(), Ws()) is True
    first = await db.collector_status()
    assert await heartbeat.write_once(db, rcv, Poller(), None) is True
    second = await db.collector_status()
    async with db.pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM collector_status") == 1
    assert second["updated_at"] > first["updated_at"]
    assert first["version"] == lutetia.__version__ and first["ws_connected"] is True and first["polling"] is True
    assert second["ws_connected"] is None  # no dingtek ws object = not enabled
    assert 0 <= first["age_sec"] < 60
    assert first["push_last_at"] == wall
    assert first["details"] == {"received": 1, "stored": 2, "rejected": 3, "unrecognised": 4, "alarms": 5, "failed": 6,
                                "queued": 7, "silent_sec": 1.5, "message_silent_sec": 2.5,
                                "collector_started_at": heartbeat.PROCESS_STARTED_AT.isoformat()}


async def test_push_count_24h_counts_only_push_origin_rows(db):
    dev = "zz-test-hb-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("gps51", dev, "zz-test-hb", "t", True, {})])
    await heartbeat.write_once(db, Rcv(), Poller(), None)
    base = (await db.collector_status())["push_count_24h"]
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    def row(ms, origin):
        return GpsPosition(dev, ms, ms, ms, 22.5, 114.0, 1.0, 0, 0.0, 0.0, 0, 0, None, None, 1, None, None, None, None, origin, {})
    try:
        await db.insert_gps_positions([row(now_ms - 1000, "push"), row(now_ms - 2000, "poll"),
                                       row(now_ms - 3000 - 48 * 3600 * 1000, "push")])
        async with db.pool.acquire() as conn:  # the third row "arrived" 48 h ago: outside the window whatever its position time
            await conn.execute("UPDATE gps_position SET ingested_at = now() - interval '48 hours' WHERE device_id = $1 AND update_time < $2",
                               dev, datetime.fromtimestamp((now_ms - 40 * 3600 * 1000) / 1000, timezone.utc))
        await heartbeat.write_once(db, Rcv(), Poller(), None)
        assert (await db.collector_status())["push_count_24h"] == base + 1
    finally:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM gps_position WHERE device_id = $1", dev)
            await conn.execute("DELETE FROM device WHERE device_id = $1", dev)


async def test_push_last_at_not_erased_by_a_beat_without_push(db):
    wall = datetime.now(timezone.utc) - timedelta(minutes=5)
    rcv = Rcv()
    rcv.last_position_wall = wall
    await heartbeat.write_once(db, rcv, Poller(), None)
    await heartbeat.write_once(db, Rcv(), Poller(), None)  # a fresh receiver (restart) has no push yet
    assert (await db.collector_status())["push_last_at"] == wall


# ---- web side, end to end ----
def make_app(db):
    cfg = dataclasses.replace(Config.from_env(), dashboard_pwd=PWD, api_key=KEY, dashboard_host="127.0.0.1")
    return WebServer(cfg, db, None, datetime.now(timezone.utc)).build_app()


async def _set_age(db, sec):
    await heartbeat.write_once(db, Rcv(), Poller(), Ws())
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE collector_status SET updated_at = now() - make_interval(secs => $1) WHERE id = 1", float(sec))


async def _login(client):
    await client.post("/login", data={"username": "admin", "password": PWD, "next": ""}, allow_redirects=False)


@pytest.mark.parametrize("age,red", [(60, False), (91, True)])
async def test_overview_heartbeat_age_drives_red_item(db, age, red):
    await _set_age(db, age)
    async with TestClient(TestServer(make_app(db))) as client:
        await _login(client)
        body = await (await client.get("/dashboard/data/overview")).json()
    got = [a for a in body["anomalies"] if a["kind"] == "collector"]
    assert bool(got) is red
    c = body["collector"]
    assert c["stale"] is red and c["ws_connected"] is True and c["polling"] is True and c["version"] == lutetia.__version__
    assert body["receiver"]["queued"] == 7 and body["receiver"]["silent_sec"] >= age + 1.0


async def test_overview_without_heartbeat_row(db):
    async with TestClient(TestServer(make_app(db))) as client:
        await _login(client)
        body = await (await client.get("/dashboard/data/overview")).json()
        assert body["receiver"] is None and body["collector"]["updated_at"] is None and body["collector"]["stale"] is True
        assert [a["detail"] for a in body["anomalies"] if a["kind"] == "collector"] == ["采集从未上报心跳"]
        html = await (await client.get("/dashboard/")).text()
        assert 'id="collector-line"' in html and "采集从未上报心跳" in html


async def test_dashboard_html_marks_old_values_when_heartbeat_stale(db):
    for age, stale in ((60, False), (91, True)):
        await _set_age(db, age)
        async with TestClient(TestServer(make_app(db))) as client:
            await _login(client)
            html = await (await client.get("/dashboard/")).text()
        assert html.count("WS 已连") == 1
        if stale:  # SV-1: every "WS 已连" must sit behind a 最后已知 qualifier, and the red bar is there too
            assert "最后已知" in html and html.index("最后已知") < html.index("WS 已连")
            assert "采集心跳已过期" in html and "[采集]" in html and "接收端计数为最后已知值" in html
        else:
            assert "最后已知" not in html and "采集心跳：" in html and "[采集]" not in html


async def test_age_uses_database_clock_only(db):
    # future stamp (2 days ahead) then 91 s ago: the second state must be red with no web-side clock involved
    await heartbeat.write_once(db, Rcv(), Poller(), Ws())
    async with db.pool.acquire() as conn:
        await conn.execute("UPDATE collector_status SET updated_at = now() + interval '2 days' WHERE id = 1")
    row = await db.collector_status()
    assert row["age_sec"] < 0 and heartbeat_view(row)[1]["stale"] is False
    await _set_age(db, 91)
    row = await db.collector_status()
    assert 91 <= row["age_sec"] < 95
    receiver, collector = heartbeat_view(row)
    assert collector["stale"] is True
    async with TestClient(TestServer(make_app(db))) as client:
        await _login(client)
        body = await (await client.get("/dashboard/data/overview")).json()
    assert [a["kind"] for a in body["anomalies"]].count("collector") == 1


async def test_first_beat_is_written_immediately(db):
    task = asyncio.create_task(heartbeat.heartbeat_loop(db, Rcv(), Poller(), lambda: None))
    try:
        for _ in range(50):  # far below HEARTBEAT_SEC: the row must exist without waiting for the first sleep to end
            await asyncio.sleep(0.1)
            if await db.collector_status():
                break
        assert await db.collector_status() is not None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_push_count_uses_arrival_time_not_position_time(db):
    # a push row whose device clock is 3 days old but which arrived just now still counts (channel health = what we received)
    dev = "zz-test-hb-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("gps51", dev, "zz-test-hb", "t", True, {})])
    await heartbeat.write_once(db, Rcv(), Poller(), None)
    base = (await db.collector_status())["push_count_24h"]
    old_ms = int((datetime.now(timezone.utc) - timedelta(days=3)).timestamp() * 1000)
    try:
        await db.insert_gps_positions([GpsPosition(dev, old_ms, old_ms, old_ms, 22.5, 114.0, 1.0, 0, 0.0, 0.0, 0, 0, None, None, 1,
                                                   None, None, None, None, "push", {})])
        await heartbeat.write_once(db, Rcv(), Poller(), None)
        assert (await db.collector_status())["push_count_24h"] == base + 1
    finally:
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM gps_position WHERE device_id = $1", dev)
            await conn.execute("DELETE FROM device WHERE device_id = $1", dev)


async def test_dashboard_page_and_api_status_read_heartbeat(db):
    await _set_age(db, 5)
    async with TestClient(TestServer(make_app(db))) as client:
        await _login(client)
        html = await (await client.get("/dashboard/")).text()
        assert "WS 已连" in html and "轮询中" in html and 'id="tbl-receiver"' in html
        r = await client.get("/api/v1/status", headers={"Authorization": "Bearer " + KEY})
        body = await r.json()
    assert r.status == 200 and "started_at" in body
    assert body["receiver"]["received"] == 1 and body["collector"]["stale"] is False
