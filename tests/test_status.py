# risk: high
"""cmd_status 失联判定与退出码（FLOW-3：运维唯一告警入口）。真库，只碰 test-status- 前缀的行。
本机库里真实设备可能本来就是 STALE，所以 device_status 在用例内被过滤成只剩自己的设备（SQL 本身照跑）。"""
import dataclasses
import os
import re
import time
import types
import uuid as uuidlib

import pytest

import lutetia.cli as cli
from lutetia.config import Config, load_dotenv
from lutetia.db import Database
from lutetia.models import Attribute, Device, Telemetry

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
ARGS = types.SimpleNamespace(max_age_hours=3)
STALE_SUMMARY = re.compile(r"^1 expected-online device\(s\) without recent data", re.M)


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


@pytest.fixture
def only_test_rows(monkeypatch):
    orig = Database.device_status

    async def filtered(self):
        return [r for r in await orig(self) if r["device_id"].startswith("test-status-")]
    monkeypatch.setattr(cli.Database, "device_status", filtered)


def _cfg(url=None):
    return dataclasses.replace(Config.from_env(), database_url=url or DB_URL)


def _line(out, dev):
    lines = [ln for ln in out.splitlines() if dev in ln]
    assert len(lines) == 1, "输出里应恰有一行含 %s: %s" % (dev, out)
    return lines[0]


async def _make(db, dev, expected, hours_ago=None, upload_interval=None):
    await db.upsert_devices([Device("dingtek", dev, "test", "DC414", None, {})])
    await db.set_expected_online("dingtek", dev, expected)
    if hours_ago is not None:
        ts = int((time.time() - hours_ago * 3600) * 1000)
        await db.insert_telemetry([Telemetry(dev, "volt", ts, 3.6, None, "rest")])
    if upload_interval is not None:
        await db.upsert_attributes([Attribute(dev, "uploadInterval", upload_interval, None)])


async def _cleanup(db, dev):
    async with db.pool.acquire() as conn:
        for t in ("sensor_telemetry", "sensor_attribute", "device"):
            await conn.execute("DELETE FROM %s WHERE device_id = $1" % t, dev)


async def test_expected_online_without_data_is_stale_and_exit_1(db, only_test_rows, capsys):
    # risk: high  (在线设备无数据必须报警，漏报要人跑现场)
    dev = "test-status-" + str(uuidlib.uuid4())
    try:
        await _make(db, dev, True)
        rc = await cli.cmd_status(_cfg(), ARGS)
        out = capsys.readouterr().out
        assert rc == 1
        assert "STALE" in _line(out, dev)
        assert STALE_SUMMARY.search(out), out
    finally:
        await _cleanup(db, dev)


async def test_not_expected_online_without_data_is_not_stale(db, only_test_rows, capsys):
    # risk: high  (从未上线的设备不许误报)
    dev = "test-status-" + str(uuidlib.uuid4())
    try:
        await _make(db, dev, False)
        rc = await cli.cmd_status(_cfg(), ARGS)
        out = capsys.readouterr().out
        assert rc == 0
        assert "STALE" not in out
        assert "without recent data" not in out
    finally:
        await _cleanup(db, dev)


async def test_upload_interval_widens_stale_threshold(db, only_test_rows, capsys):
    # risk: high  (2 小时一报的传感器 3.5 小时没数据不算失联；无 uploadInterval 则算)
    dev = "test-status-" + str(uuidlib.uuid4())
    try:
        await _make(db, dev, True, hours_ago=3.5, upload_interval="2")
        rc = await cli.cmd_status(_cfg(), ARGS)
        out = capsys.readouterr().out
        assert rc == 0
        assert "STALE" not in _line(out, dev)
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM sensor_attribute WHERE device_id = $1", dev)
        rc = await cli.cmd_status(_cfg(), ARGS)
        out = capsys.readouterr().out
        assert rc == 1
        assert "STALE" in _line(out, dev)
    finally:
        await _cleanup(db, dev)


async def test_unreachable_database_raises_and_never_says_all_ok(capsys):
    # risk: high  (库连不上不能静默成"全部正常")
    with pytest.raises(Exception):
        await cli.cmd_status(_cfg("postgresql://lutetia:lutetia@127.0.0.1:1/lutetia"), ARGS)
    out = capsys.readouterr().out
    assert out == "", out  # 连接失败发生在任何输出之前
