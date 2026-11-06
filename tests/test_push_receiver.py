# risk: high
"""PushReceiver: 写库失败不丢推送(F2)、停机先清队列(F3)、空体400/认不出计数/health字段(F7)。
断言按 Phase 1 修复契约的修后行为写，不迁就现有实现。全部 stub，无网络。"""
import asyncio
import logging
import re
import time
from pathlib import Path

import asyncpg
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import lutetia.sources.gps51 as g
from lutetia.config import Config

PUSH = {"deviceid": "4072400634", "lat": 48.83, "lon": 2.26, "updatetime": 1793900000000, "arrivedtime": 1793900000500}


def make_cfg(state_dir: Path) -> Config:
    return Config(database_url="x", gps51_user="u", gps51_pwd="p", gps51_api_base="http://127.0.0.1:1/openapi",
                  gps51_daily_budget=1400, gps51_poll_interval=0, gps51_min_call_gap=0.0, push_silence_min=0,
                  push_host="127.0.0.1", push_port=0, push_path="/gps51/push", dingtek_user="u", dingtek_pwd="p",
                  dingtek_base="http://127.0.0.1:1", dingtek_reconcile_hour_utc=3, state_dir=state_dir, log_level="INFO")


class StubDB:
    """insert 按 script 逐次动作：异常实例 -> 抛；None -> 成功返回行数。脚本用完后一律成功。"""
    def __init__(self, script=None, always=None):
        self.script, self.always, self.calls = list(script or []), always, 0

    async def insert_gps_positions(self, rows):
        self.calls += 1
        if self.always is not None:
            raise self.always
        if self.script:
            act = self.script.pop(0)
            if act is not None:
                raise act
        return len(rows)


@pytest.fixture
def sleeps(monkeypatch):
    """记录 >=1s 的 sleep（退避），实际只睡 10ms，避免用例变慢。"""
    rec, real = [], asyncio.sleep

    async def fake(d, *a, **k):
        if d >= 1:
            rec.append(d)
            d = 0.01
        return await real(d, *a, **k)
    monkeypatch.setattr(g.asyncio, "sleep", fake)
    return rec


async def _drain(rc, timeout=5):
    await asyncio.wait_for(rc.queue.join(), timeout)


async def test_f2_db_error_retries_same_payload_until_stored(tmp_path, sleeps):
    # risk: high  (Spec: 丢一行就是永久丢)
    db = StubDB(script=[ConnectionError("pg down"), ConnectionError("pg down")])
    rc = g.PushReceiver(make_cfg(tmp_path), db)
    rc._consumer = asyncio.create_task(rc._consume())
    try:
        rc.queue.put_nowait(PUSH)
        await _drain(rc)
        assert rc.stored == 1, "写库前两次失败，同一条推送应原地重试直到成功；stored=%s" % rc.stored
        assert rc.queue.qsize() == 0
        assert getattr(rc, "failed", 0) == 0
        assert sleeps == [1, 2], "退避序列应为 [1, 2]，实际 %s" % sleeps
        assert db.calls == 3
    finally:
        rc._consumer.cancel()


async def test_f2_non_db_error_counts_failed_and_continues(tmp_path, sleeps):
    # risk: high
    db = StubDB(script=[RuntimeError("parser bug"), None])
    rc = g.PushReceiver(make_cfg(tmp_path), db)
    rc._consumer = asyncio.create_task(rc._consume())
    try:
        rc.queue.put_nowait(PUSH)
        rc.queue.put_nowait(dict(PUSH, updatetime=PUSH["updatetime"] + 1))
        await _drain(rc)
        assert getattr(rc, "failed", None) == 1, "非 DB 类异常应 failed += 1"
        assert rc.stored == 1, "丢弃坏的一条后应继续消费下一条"
        assert sleeps == [], "非 DB 类异常不应退避重试"
    finally:
        rc._consumer.cancel()


async def test_f3_stop_drains_queue_before_cancel(tmp_path):
    # risk: high
    db = StubDB()
    rc = g.PushReceiver(make_cfg(tmp_path), db)
    rc._consumer = asyncio.create_task(rc._consume())
    for i in range(3):
        rc.queue.put_nowait(dict(PUSH, updatetime=PUSH["updatetime"] + i))
    await asyncio.wait_for(rc.stop(), 5)
    assert rc.stored == 3, "stop() 应先把队列写完；stored=%s" % rc.stored
    assert rc.queue.qsize() == 0


async def test_f3_stop_gives_up_after_drain_timeout_and_logs_remaining(tmp_path, sleeps, caplog):
    # risk: high
    rc = g.PushReceiver(make_cfg(tmp_path), StubDB(always=ConnectionError("pg down")))
    rc.drain_timeout = 0.5
    rc._consumer = asyncio.create_task(rc._consume())
    for i in range(2):
        rc.queue.put_nowait(dict(PUSH, updatetime=PUSH["updatetime"] + i))
    await asyncio.sleep(0.05)
    caplog.set_level(logging.INFO)
    t0 = time.monotonic()
    await asyncio.wait_for(rc.stop(), 5)
    elapsed = time.monotonic() - t0
    assert 0.3 <= elapsed < 3.0, "DB 一直挂时 stop() 应在 drain_timeout(0.5s) 附近返回，实际 %.2fs" % elapsed
    errs = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(re.search(r"\b2 remaining pushes lost", m) for m in errs), "超时应 log.error 带剩余条数，实际 error 行: %s" % errs


def _client(rc):
    app = web.Application()
    app.router.add_post("/gps51/push", rc._handle)
    app.router.add_get("/health", rc._health)
    return TestClient(TestServer(app))


async def test_f7_empty_body_is_400_and_does_not_refresh_silence(tmp_path):
    # risk: high  (空体不能骗过静默检测，否则兜底轮询不启动)
    rc = g.PushReceiver(make_cfg(tmp_path), StubDB())
    async with _client(rc) as cl:
        r = await cl.post("/gps51/push", data=b"")
        assert r.status == 400
        assert rc.rejected == 1
        assert rc.last_push_at is None


async def test_f7_unrecognised_payload_counted_not_stored(tmp_path):
    # risk: high
    db = StubDB()
    rc = g.PushReceiver(make_cfg(tmp_path), db)
    rc._consumer = asyncio.create_task(rc._consume())
    try:
        async with _client(rc) as cl:
            r = await cl.post("/gps51/push", json={"hello": "world"})
            assert r.status == 200
            await _drain(rc)
            assert getattr(rc, "unrecognised", None) == 1
            assert db.calls == 0
    finally:
        rc._consumer.cancel()


async def test_f7_health_exposes_unrecognised_and_failed(tmp_path):
    # risk: medium
    rc = g.PushReceiver(make_cfg(tmp_path), StubDB())
    async with _client(rc) as cl:
        body = await (await cl.get("/health")).json()
    for k in ("status", "received", "stored", "rejected", "queued", "silent_sec"):
        assert k in body, "现有字段 %s 不得改名" % k
    assert isinstance(body.get("unrecognised"), int)
    assert isinstance(body.get("failed"), int)


async def test_f2b_server_data_error_is_dropped_not_retried(tmp_path, sleeps):
    # risk: high  (F2b: 数据本身有问题的推送不能无限重试卡死整条队列)
    db = StubDB(script=[asyncpg.DataError("bad value"), None])
    rc = g.PushReceiver(make_cfg(tmp_path), db)
    rc._consumer = asyncio.create_task(rc._consume())
    try:
        rc.queue.put_nowait(PUSH)
        rc.queue.put_nowait(dict(PUSH, updatetime=PUSH["updatetime"] + 1))
        await _drain(rc)
        assert getattr(rc, "failed", None) == 1, "服务端 DataError 应丢弃并 failed += 1"
        assert sleeps == [], "数据类错误不应退避重试；实际 sleep %s" % sleeps
        assert rc.stored == 1, "第二条正常推送应入库；stored=%s" % rc.stored
        assert db.calls == 2
    finally:
        rc._consumer.cancel()


@pytest.mark.parametrize("exc", [
    asyncpg.ConnectionDoesNotExistError("x"),
    asyncpg.CannotConnectNowError("x"),
    asyncpg.InterfaceError("connection is closed"),
    ConnectionRefusedError(),
    asyncio.TimeoutError(),
], ids=["ConnectionDoesNotExist", "CannotConnectNow", "InterfaceError", "ConnectionRefused", "AsyncioTimeout"])
async def test_f2b_connection_class_errors_are_retried(tmp_path, sleeps, exc):
    # risk: high  (连接类故障必须原地重试，否则 pg 重启丢数据)
    db = StubDB(script=[exc, None])
    rc = g.PushReceiver(make_cfg(tmp_path), db)
    rc._consumer = asyncio.create_task(rc._consume())
    try:
        rc.queue.put_nowait(PUSH)
        await _drain(rc)
        assert rc.stored == 1, "连接类异常应重试到成功；stored=%s" % rc.stored
        assert sleeps == [1], "退避应为 [1]，实际 %s" % sleeps
        assert getattr(rc, "failed", 0) == 0
    finally:
        rc._consumer.cancel()


# ---- Task 2.2: 静默按位置算 + 报警只计数 ----
class ZeroDB(StubDB):
    """insert 一律返回 0（重复投递）。"""
    async def insert_gps_positions(self, rows):
        self.calls += 1
        return 0


ALARM = {"deviceid": "4072400634", "alarmtype": 1, "stralarm": "SOS", "lat": 48.83, "lon": 2.26,
         "updatetime": 1793900002000}


async def _post_and_drain(rc, payload):
    async with _client(rc) as cl:
        r = await cl.post("/gps51/push", json=payload)
        assert r.status == 200
        await _drain(rc)


async def test_alarm_payload_counted_not_stored_and_does_not_reset_position_silence(tmp_path):
    # risk: high
    db = StubDB()
    rc = g.PushReceiver(make_cfg(tmp_path), db)
    rc.started_at -= 100
    rc._consumer = asyncio.create_task(rc._consume())
    try:
        await _post_and_drain(rc, ALARM)
        assert rc.alarms == 1
        assert db.calls == 0
        assert rc.unrecognised == 0
        assert rc.silent_for() > 99, "报警不是位置，位置静默不得归零；实际 %s" % rc.silent_for()
        assert rc.message_silent_for() < 1
    finally:
        rc._consumer.cancel()


async def test_position_payload_resets_position_silence_even_if_duplicate(tmp_path):
    # risk: high
    db = ZeroDB()
    rc = g.PushReceiver(make_cfg(tmp_path), db)
    rc.started_at -= 100
    rc._consumer = asyncio.create_task(rc._consume())
    try:
        await _post_and_drain(rc, PUSH)
        assert db.calls == 1
        assert rc.silent_for() < 1
    finally:
        rc._consumer.cancel()


async def test_unrecognised_payload_does_not_reset_position_silence(tmp_path):
    # risk: high
    rc = g.PushReceiver(make_cfg(tmp_path), StubDB())
    rc.started_at -= 100
    rc._consumer = asyncio.create_task(rc._consume())
    try:
        await _post_and_drain(rc, {"hello": "world"})
        assert rc.unrecognised == 1
        assert rc.silent_for() > 99
    finally:
        rc._consumer.cancel()


async def test_health_has_alarms_and_message_silent_sec(tmp_path):
    # risk: medium
    rc = g.PushReceiver(make_cfg(tmp_path), StubDB())
    async with _client(rc) as cl:
        body = await (await cl.get("/health")).json()
    assert isinstance(body.get("alarms"), int)
    assert isinstance(body.get("message_silent_sec"), int)
