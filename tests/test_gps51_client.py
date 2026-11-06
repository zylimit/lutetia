# risk: high
"""Gps51Poller 游标先入库再推进 + 日志累计次数(F4)、登录失败退避(F5)、超时也计 api_call(F6)。stub，无网络。"""
import asyncio
import json
import logging
import time
from pathlib import Path
from types import SimpleNamespace

import aiohttp
import pytest

import lutetia.sources.gps51 as g
from lutetia.config import Config

PUSH = {"deviceid": "4072400634", "lat": 48.83, "lon": 2.26, "updatetime": 1793900000000, "arrivedtime": 1793900000500}


def make_cfg(state_dir: Path) -> Config:
    return Config(database_url="x", gps51_user="u", gps51_pwd="p", gps51_api_base="http://127.0.0.1:1/openapi",
                  gps51_daily_budget=1400, gps51_poll_interval=0, gps51_min_call_gap=0.0, push_silence_min=0,
                  push_host="127.0.0.1", push_port=0, push_path="/gps51/push", dingtek_user="u", dingtek_pwd="p",
                  dingtek_base="http://127.0.0.1:1", dingtek_reconcile_hour_utc=3, state_dir=state_dir, log_level="INFO")


class StubDB:
    def __init__(self, insert_exc=None):
        self.insert_exc, self.api, self.inserted = insert_exc, [], []

    async def record_api_call(self, s, a, ok):
        self.api.append((s, a, ok))

    async def api_calls_since(self, s, since, action=None):
        return 0

    async def insert_gps_positions(self, rows):
        if self.insert_exc:
            raise self.insert_exc
        self.inserted += rows
        return len(rows)


class FakeClient:
    async def lastposition(self, t):
        return {"status": 0, "lastquerypositiontime": 999, "records": [dict(PUSH, callat=1, callon=2)]}


async def test_f4_cursor_not_advanced_when_insert_fails():
    # risk: high  (游标先走、入库失败 = 这批永久跳过)
    p = g.Gps51Poller(FakeClient(), StubDB(insert_exc=RuntimeError("db write failed")))
    with pytest.raises(RuntimeError):
        await p.poll_once()
    assert p.last_query_time == 0, "insert 失败时游标必须原地不动；实际 %s" % p.last_query_time


async def test_f4_cursor_advances_after_insert_and_log_has_poll_count(caplog):
    # risk: high
    caplog.set_level(logging.INFO)
    p = g.Gps51Poller(FakeClient(), StubDB())
    await p.poll_once()
    assert p.last_query_time == 999
    assert any(r.getMessage().startswith("gps51 poll #1:") for r in caplog.records), \
        "日志应为 'gps51 poll #1: N records, M new'，实际: %s" % [r.getMessage() for r in caplog.records]


class Resp:
    def __init__(self, body):
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def text(self):
        return json.dumps(self.body)


class LoginFailSession:
    def __init__(self):
        self.urls = []

    def post(self, url, json=None, timeout=None):
        self.urls.append(url)
        return Resp({"status": 8904, "cause": "ip not in whitelist"})


async def test_f5_login_failure_backoff_does_not_hit_network(tmp_path, monkeypatch):
    # risk: high  (登录失败每 60s 重试会烧光日配额)
    # 不能直接 patch 全局 time.monotonic（事件循环也用它），换成模块内的 time 垫片
    monkeypatch.setattr(g, "time", SimpleNamespace(monotonic=lambda: 1000.0, time=time.time))
    sess, db = LoginFailSession(), StubDB()
    c = g.Gps51Client(make_cfg(tmp_path), db, sess)
    for _ in range(10):
        with pytest.raises(g.Gps51Error):
            await c.ensure_token()
    logins = [u for u in sess.urls if "action=login" in u]
    assert len(logins) == 1, "退避期内不应再发 login 请求；实际真实 login 请求 %d 次" % len(logins)


@pytest.mark.parametrize("exc", [asyncio.TimeoutError(), aiohttp.ClientConnectionError("reset")])
async def test_f6_network_errors_are_recorded_as_failed_api_call(tmp_path, exc):
    # risk: high  (配额守护靠 api_call 表，漏记 = 低估用量)
    class Sess:
        def post(self, url, json=None, timeout=None):
            raise exc

    db = StubDB()
    c = g.Gps51Client(make_cfg(tmp_path), db, Sess())
    c._token, c._serverid, c._obtained_at = "T", 1, time.time()
    got = None
    try:
        await c.call("lastposition", {})
    except BaseException as e:  # noqa: BLE001
        got = e
    assert db.api == [("gps51", "lastposition", False)], "超时/网络异常也应记一条 ok=False；实际 %s" % db.api
    assert isinstance(got, g.Gps51Error), "调用方应拿到 Gps51Error，实际 %r" % got
