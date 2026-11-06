# risk: high
"""DingtekWs: 日志不泄露 JWT(F1)、重连退避真指数增长 + errorCode=3 不反复登录(F9)。本机 aiohttp WS 服务，无外网。"""
import asyncio
import json
import logging
import time

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

import lutetia.sources.dingtek as dk

SECRET = "eyJhbGciOiJIUzUxMiJ9.eyJleHAiOjk5OTk5OTk5OTl9.SECRETSIG"


class StubClient:
    def __init__(self, base):
        self.cfg = type("C", (), {"dingtek_base": base})()
        self.token = SECRET
        self.token_obtained_at = time.monotonic()   # F9: 刚拿到的 token
        self.inval = 0

    async def ensure_token(self):
        pass

    async def invalidate(self):
        self.inval += 1


class StubDB:
    async def insert_telemetry(self, rows):
        return len(rows)


class StopRun(BaseException):
    pass


def patch_sleep(monkeypatch, stop_after):
    """记录 >=1s 的 sleep；记到 stop_after 次后用 CancelledError 终止 run()。其余 sleep 近乎立即返回。"""
    rec, real = [], asyncio.sleep

    async def fake(d, *a, **k):
        if d >= 1:
            rec.append(d)
            if len(rec) >= stop_after:
                raise asyncio.CancelledError()
            d = 0
        return await real(d, *a, **k)
    monkeypatch.setattr(dk.asyncio, "sleep", fake)
    return rec


async def serve(handler):
    app = web.Application()
    app.router.add_get("/api/ws/plugins/telemetry", handler)
    srv = TestServer(app)
    await srv.start_server()
    return srv, "http://127.0.0.1:%d" % srv.port


async def run_until_cancel(ws, timeout=8):
    try:
        await asyncio.wait_for(ws.run(), timeout)
    except asyncio.CancelledError:
        pass


async def test_f1_handshake_401_does_not_leak_jwt_into_logs(monkeypatch, caplog):
    # risk: high  (H-1: URL 带 ?token=，日志泄露 = 凭据泄露)
    async def h401(req):
        return web.Response(status=401, text="unauthorized")
    srv, base = await serve(h401)
    caplog.set_level(logging.DEBUG)
    patch_sleep(monkeypatch, 1)
    try:
        cl = StubClient(base)
        async with aiohttp.ClientSession() as s:
            await run_until_cancel(dk.DingtekWs(cl, StubDB(), s, ["uuid-1"]))
    finally:
        await srv.close()
    # 只看被测代码的 logger；aiohttp.access 是测试服务端自己的访问日志，URL 里本来就带 token，不属被测范围
    recs = [r for r in caplog.records if r.name == "lutetia.sources.dingtek"]
    text = "\n".join(r.getMessage() + (r.exc_text or "") + str(r.exc_info and r.exc_info[1]) for r in recs)
    assert SECRET not in text and "SECRETSIG" not in text, "日志中出现了 JWT"
    assert any("401" in r.getMessage() for r in recs), "握手失败应至少有一条日志带 401"


async def test_f9_backoff_doubles_when_server_closes_immediately(monkeypatch):
    # risk: high  (M-4: 一连上就关时退避被重置成 5s，等于每 5s 打一次厂家)
    async def hclose(req):
        w = web.WebSocketResponse()
        await w.prepare(req)
        await w.close()
        return w
    srv, base = await serve(hclose)
    sleeps = patch_sleep(monkeypatch, 4)
    try:
        async with aiohttp.ClientSession() as s:
            await run_until_cancel(dk.DingtekWs(StubClient(base), StubDB(), s, ["uuid-1"]))
    finally:
        await srv.close()
    assert sleeps == [5, 10, 20, 40], "短会话不得重置退避，应 5→10→20→40；实际 %s" % sleeps


async def test_f9_errorcode3_right_after_fresh_login_does_not_invalidate(monkeypatch):
    # risk: high  (M-4: errorCode=3 每轮 invalidate = 每轮真登录，触发厂家 5 次/分限流)
    async def herr3(req):
        w = web.WebSocketResponse()
        await w.prepare(req)
        await w.receive()
        await w.send_str(json.dumps({"subscriptionId": 1, "errorCode": 3, "errorMsg": "Unauthorized"}))
        await asyncio.sleep(0.05)
        return w
    srv, base = await serve(herr3)
    patch_sleep(monkeypatch, 1)
    cl = StubClient(base)          # token_obtained_at = 刚刚
    try:
        async with aiohttp.ClientSession() as s:
            await run_until_cancel(dk.DingtekWs(cl, StubDB(), s, ["uuid-1"]))
    finally:
        await srv.close()
    assert cl.inval == 0, "token 刚拿到 <120s 时 errorCode=3 不应 invalidate；实际调了 %d 次" % cl.inval
