# risk: high
"""Phase 4 Task 4.2 contract 1-10: homepage anomaly overview (pure rules + overview endpoint + config)."""
import dataclasses
import os
import uuid as uuidlib
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config, load_dotenv
from lutetia.db import Database
from lutetia.models import Device
from lutetia.web import WebServer

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
PWD = "pw-test"
NOW = datetime(2026, 11, 7, 12, 0, 0, tzinfo=timezone.utc)


def _anom():
    from lutetia.web import anomalies
    return anomalies


def dev(device_id="d1", name="井盖A", expected_online=True, last_ts=None, upload_interval_h=None):
    return {"source": "dingtek", "device_id": device_id, "name": name, "expected_online": expected_online,
            "last_ts": last_ts, "upload_interval_h": upload_interval_h}


def run(devices=(), sensor=(), alarms=(), receiver=None, calls=(), budget=1400, low_volt=3.4):
    return _anom().compute(NOW, list(devices), list(sensor), list(alarms), receiver, list(calls),
                           budget, low_volt)


def kinds(items, kind):
    return [i for i in items if i["kind"] == kind]


def volt(v, device_id="d1", name="井盖A"):
    return {"device_id": device_id, "name": name, "key": "volt", "value_si": v, "ts": NOW}


def alarm(key, v, device_id="d1", name="井盖A"):
    return {"device_id": device_id, "name": name, "key": key, "value_num": v, "ts": NOW}


def test_compute_empty_is_all_ok():
    assert run() == []
    assert _anom().summarize([]) == "全部正常"


def test_stale_rule_uses_max_age_and_upload_interval():
    a = _anom()
    # 无数据 -> red stale
    items = run([dev(last_ts=None)])
    st = kinds(items, "stale")
    assert len(st) == 1 and st[0]["level"] == a.LEVEL_RED and st[0]["device_id"] == "d1"
    # upload_interval_h=2 -> 阈值 4h，3.5h 前不报
    assert kinds(run([dev(last_ts=NOW - timedelta(hours=3.5), upload_interval_h=2)]), "stale") == []
    # 无 upload_interval -> 阈值 3h，3.5h 前报
    st = kinds(run([dev(last_ts=NOW - timedelta(hours=3.5))]), "stale")
    assert len(st) == 1 and st[0]["level"] == a.LEVEL_RED
    # expected_online False -> 不报（含无数据）
    assert kinds(run([dev(expected_online=False, last_ts=None)]), "stale") == []
    assert kinds(run([dev(expected_online=False, last_ts=NOW - timedelta(hours=9))]), "stale") == []


def test_low_volt_levels():
    a = _anom()
    y = kinds(run(sensor=[volt(3.35)]), "low_volt")
    assert len(y) == 1 and y[0]["level"] == a.LEVEL_YELLOW and "3.35" in y[0]["detail"]
    r = kinds(run(sensor=[volt(3.1)]), "low_volt")
    assert len(r) == 1 and r[0]["level"] == a.LEVEL_RED
    assert kinds(run(sensor=[volt(3.6)]), "low_volt") == []


def test_alarm_rule():
    a = _anom()
    items = kinds(run(alarms=[alarm("alarmFall", 1), alarm("alarmLevel", 0), alarm("alarmBattery", 0)]), "alarm")
    assert len(items) == 1 and items[0]["level"] == a.LEVEL_RED
    assert "alarmFall=1" in items[0]["detail"]
    zero = run(alarms=[alarm("alarmFall", 0), alarm("alarmLevel", 0), alarm("alarmBattery", 0)])
    assert kinds(zero, "alarm") == []


def test_push_rule():
    a = _anom()
    r = kinds(run(receiver={"silent_sec": 901}), "push")
    assert len(r) == 1 and r[0]["level"] == a.LEVEL_RED
    assert kinds(run(receiver={"silent_sec": 899}), "push") == []
    assert kinds(run(receiver=None), "push") == []


def test_quota_levels():
    a = _anom()

    def calls(n):
        return [{"source": "gps51", "action": "lastposition", "n": n}]
    y = kinds(run(calls=calls(1120)), "quota")
    assert len(y) == 1 and y[0]["level"] == a.LEVEL_YELLOW
    r = kinds(run(calls=calls(1400)), "quota")
    assert len(r) == 1 and r[0]["level"] == a.LEVEL_RED
    assert kinds(run(calls=calls(1000)), "quota") == []
    # 多个 action 合计后再比
    split = [{"source": "gps51", "action": "a", "n": 600}, {"source": "gps51", "action": "b", "n": 520},
             {"source": "dingtek", "action": "x", "n": 9999}]
    assert len(kinds(run(calls=split), "quota")) == 1


def test_login_rule():
    a = _anom()
    r = kinds(run(calls=[{"source": "dingtek", "action": "login", "n": 2}]), "login")
    assert len(r) == 1 and r[0]["level"] == a.LEVEL_RED
    assert kinds(run(calls=[{"source": "dingtek", "action": "login", "n": 1}]), "login") == []


def test_sorting_red_first():
    a = _anom()
    items = run(devices=[dev("d2", "乙", last_ts=None), dev("d1", "甲", last_ts=None)],
                sensor=[volt(3.35, "d3", "丙")],  # yellow
                receiver={"silent_sec": 2000},
                calls=[{"source": "gps51", "action": "a", "n": 1200}])  # yellow quota
    levels = [i["level"] for i in items]
    assert set(levels) == {a.LEVEL_RED, a.LEVEL_YELLOW}
    first_yellow = levels.index(a.LEVEL_YELLOW)
    assert all(l == a.LEVEL_RED for l in levels[:first_yellow])
    assert all(l == a.LEVEL_YELLOW for l in levels[first_yellow:])
    reds = [i for i in items if i["level"] == a.LEVEL_RED]
    key = lambda i: (a.KIND_ORDER.index(i["kind"]), i.get("name", ""))
    assert [key(i) for i in reds] == sorted(key(i) for i in reds)
    assert reds[0]["kind"] == "stale"  # 失联最前，push 不得排在 stale 前
    s = a.summarize(items)
    assert s.startswith("%d 项异常" % len(items)) and "红" in s and "黄" in s


# ---- DB / endpoint ----
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


def make_app(db):
    cfg = dataclasses.replace(Config.from_env(), dashboard_pwd=PWD, api_key="k-test", dashboard_host="127.0.0.1")
    return WebServer(cfg, db, None, datetime.now(timezone.utc)).build_app()


async def cleanup(db, dev_id):
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM sensor_telemetry WHERE device_id = $1", dev_id)
        await conn.execute("DELETE FROM gps_position WHERE device_id = $1", dev_id)
        await conn.execute("DELETE FROM device WHERE device_id = $1", dev_id)


async def test_overview_endpoint_includes_anomalies(db):
    dev_id = "test-dash-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("dingtek", dev_id, "dash-anom", "DC414", True, {})])
    try:
        async with TestClient(TestServer(make_app(db))) as client:
            await client.post("/login", data={"username": "admin", "password": PWD, "next": ""},
                              allow_redirects=False)
            body = await (await client.get("/dashboard/data/overview")).json()
            mine = [a for a in body["anomalies"] if a.get("kind") == "stale" and a.get("device_id") == dev_id]
            assert len(mine) == 1
            assert body["anomaly_summary"] != "全部正常"
            html = await (await client.get("/dashboard/", allow_redirects=False)).text()
            assert 'id="anomalies"' in html
            assert dev_id in html
    finally:
        await cleanup(db, dev_id)


def test_low_volt_config_default_and_env(monkeypatch):
    monkeypatch.delenv("DASHBOARD_LOW_VOLT", raising=False)
    # load_dotenv 不覆盖已有环境变量；此处先清掉，默认值应为 3.4
    assert Config.from_env().low_volt == pytest.approx(3.4)
    monkeypatch.setenv("DASHBOARD_LOW_VOLT", "3.3")
    assert Config.from_env().low_volt == pytest.approx(3.3)
