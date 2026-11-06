# risk: high
"""Task 2.4 contract 6-13: dashboard + login via aiohttp TestServer against the local DB (skipped when unreachable)."""
import dataclasses
import importlib
import inspect
import os
import pkgutil
import re
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


def make_app(db, cfg=None):
    return WebServer(cfg or make_cfg(), db, None, datetime.now(timezone.utc)).build_app()


async def login(client, password=PWD):
    return await client.post("/login", data={"username": "admin", "password": password, "next": ""},
                             allow_redirects=False)


async def cleanup(db, dev):
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM sensor_telemetry WHERE device_id = $1", dev)
        await conn.execute("DELETE FROM gps_position WHERE device_id = $1", dev)
        await conn.execute("DELETE FROM device WHERE device_id = $1", dev)


async def test_dashboard_requires_login(db):
    async with TestClient(TestServer(make_app(db))) as client:
        r = await client.get("/dashboard/", allow_redirects=False)
        assert r.status == 302
        assert r.headers["Location"].startswith("/login")


async def test_login_wrong_password_401_and_lock_after_five(db):
    async with TestClient(TestServer(make_app(db))) as client:
        for _ in range(5):
            r = await login(client, "wrong")
            assert r.status == 401
        r = await login(client, "wrong")
        assert r.status == 429
        # even the right password is refused while locked
        assert (await login(client, PWD)).status == 429


async def test_login_sets_cookie_and_dashboard_renders(db):
    dev = "test-dash-" + str(uuidlib.uuid4())
    await db.upsert_devices([Device("dingtek", dev, "dash-test", "DC414", True, {})])
    try:
        async with TestClient(TestServer(make_app(db))) as client:
            r = await login(client)
            assert r.status == 302
            sc = r.headers.get("Set-Cookie", "")
            assert "lutetia_session" in sc
            assert "httponly" in sc.lower()
            r = await client.get("/dashboard/", allow_redirects=False)
            assert r.status == 200
            assert r.headers["Content-Type"].startswith("text/html")
            html = await r.text()
            rows = [seg for seg in re.split(r"(?i)<tr", html) if dev in seg]
            assert rows, "device row missing"
            assert all("STALE" in seg for seg in rows)
    finally:
        await cleanup(db, dev)


async def test_dashboard_has_no_write_controls(db):
    async with TestClient(TestServer(make_app(db))) as client:
        login_html = await (await client.get("/login")).text()
        assert "<form" in login_html.lower()
        await login(client)
        r = await client.get("/dashboard/", allow_redirects=False)
        assert r.status == 200
        html = (await r.text()).lower()
        for tag in ("<form", "<button", "<input"):
            assert tag not in html



async def test_start_refuses_non_loopback_without_credentials(db):
    cfg = dataclasses.replace(Config.from_env(), dashboard_host="0.0.0.0", dashboard_pwd="", api_key="k-test")
    with pytest.raises(SystemExit):
        await WebServer(cfg, db, None, datetime.now(timezone.utc)).start()


def test_web_package_has_no_write_sql():
    pkg = importlib.import_module("lutetia.web")
    pat = re.compile(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|DROP)\b", re.IGNORECASE)
    mods = [pkg] + [importlib.import_module(m.name) for m in pkgutil.iter_modules(pkg.__path__, "lutetia.web.")]
    assert len(mods) >= 4  # __init__, app, auth, dashboard
    for m in mods:
        assert not pat.search(inspect.getsource(m)), "write keyword in %s" % m.__name__


async def test_latest_queries_return_test_rows(db):
    # W7: 传感器挂 dingtek 设备，GPS 位置挂 gps51 设备
    dev = "test-fix-" + str(uuidlib.uuid4())
    devg = "test-fix-" + str(uuidlib.uuid4())
    now_ms = int(time.time() * 1000)
    await db.upsert_devices([Device("dingtek", dev, "dash-test", "DC414", True, {}),
                             Device("gps51", devg, "dash-gps", "GT06", True, {})])
    try:
        await db.insert_telemetry([Telemetry(dev, "volt", now_ms, 3600.0, None, "rest")])
        gps = GpsPosition(devg, now_ms, now_ms, now_ms, 22.5, 114.0, 10000.0, 0, 0.0, 0.0, 0, 0,
                          None, None, 1, None, None, None, None, "poll", {})
        await db.insert_gps_positions([gps])
        sensors = await db.latest_sensor_values(("volt",))
        assert any(r["device_id"] == dev and r["key"] == "volt" for r in sensors)
        positions = await db.latest_gps_positions()
        assert any(r["device_id"] == devg and r["name"] == "dash-gps" for r in positions)
    finally:
        await cleanup(db, dev)
        await cleanup(db, devg)


# ---- 审查修复：W1 / W2 / W4 红锁 + M2 / A2 加固 ----
import asyncio  # noqa: E402
import logging  # noqa: E402
import socket  # noqa: E402

SECRET = "s" * 40
XSS = "<img src=x onerror=alert(1)>"


async def post_login(client, password, xff=None, **extra):
    headers = {"X-Forwarded-For": xff} if xff else {}
    data = {"username": "admin", "password": password, "next": ""}
    data.update(extra)
    return await client.post("/login", data=data, headers=headers, allow_redirects=False)


async def test_logout_clears_session(db):
    # risk: high  (M2: 断言服务端真发了删除 cookie 的头，不再替浏览器清 jar)
    async with TestClient(TestServer(make_app(db))) as client:
        await login(client)
        assert (await client.get("/dashboard/", allow_redirects=False)).status == 200
        r = await client.get("/logout", allow_redirects=False)
        assert r.status == 302
        sc = r.headers.get("Set-Cookie", "")
        assert "lutetia_session" in sc
        assert "max-age=0" in sc.lower()
        r = await client.get("/dashboard/", allow_redirects=False)
        assert r.status == 302
        assert r.headers["Location"].startswith("/login")


async def test_session_replay_after_logout_rejected(db):
    # risk: high  (W2: 退出后同一 cookie 重放必须失效)
    async with TestClient(TestServer(make_app(db))) as client:
        r = await login(client)
        token = r.cookies["lutetia_session"].value
        hdr = {"Cookie": "lutetia_session=" + token}
        assert (await client.get("/dashboard/", headers=hdr, allow_redirects=False)).status == 200
        await client.get("/logout", allow_redirects=False)
        r = await client.get("/dashboard/", headers=hdr, allow_redirects=False)
        assert r.status == 302
        assert r.headers["Location"].startswith("/login")


async def test_session_invalid_after_password_change(db):
    # risk: high  (W2: 改密码后旧 cookie 全部失效；同密码重建 app 的对照组仍 200，防平凡通过)
    cfg1 = make_cfg(session_secret=SECRET)
    async with TestClient(TestServer(make_app(db, cfg1))) as c1:
        token = (await login(c1)).cookies["lutetia_session"].value
    hdr = {"Cookie": "lutetia_session=" + token}
    async with TestClient(TestServer(make_app(db, make_cfg(session_secret=SECRET)))) as c2:
        assert (await c2.get("/dashboard/", headers=hdr, allow_redirects=False)).status == 200
    cfg3 = dataclasses.replace(cfg1, dashboard_pwd="changed-pw")
    async with TestClient(TestServer(make_app(db, cfg3))) as c3:
        r = await c3.get("/dashboard/", headers=hdr, allow_redirects=False)
        assert r.status == 302
        assert r.headers["Location"].startswith("/login")


async def test_lock_ignores_forged_xff_when_proxy_not_trusted(db):
    # risk: high  (W1: 换 XFF 不能绕锁，按 remote 计)
    async with TestClient(TestServer(make_app(db))) as client:
        for i in range(5):
            assert (await post_login(client, "wrong", xff="203.0.113.%d" % (i + 1))).status == 401
        assert (await post_login(client, "wrong", xff="203.0.113.99")).status == 429


async def test_lock_counts_by_xff_when_proxy_trusted(db):
    # risk: high  (W1: remote 回环 + trust_proxy → 按 XFF 计，各来源互不牵连)
    cfg = make_cfg(trust_proxy=True)
    async with TestClient(TestServer(make_app(db, cfg))) as client:
        for _ in range(5):
            assert (await post_login(client, "wrong", xff="203.0.113.5")).status == 401
        assert (await post_login(client, "wrong", xff="203.0.113.5")).status == 429
        assert (await post_login(client, "wrong", xff="203.0.113.77")).status == 401


async def test_global_lock_across_ips_when_proxy_trusted(db):
    # risk: high  (W1: 全局兜底，60 次各异来源失败后换 IP 也 429，正确密码同样被拒)
    cfg = make_cfg(trust_proxy=True)
    async with TestClient(TestServer(make_app(db, cfg))) as client:
        for i in range(60):
            await post_login(client, "wrong", xff="198.51.%d.%d" % (i // 250, i % 250 + 1))
        r = await post_login(client, "wrong", xff="192.0.2.200")
        assert r.status == 429
        assert (await post_login(client, PWD, xff="192.0.2.201")).status == 429


async def test_login_page_does_not_echo_script(db):
    # risk: high  (A2: 三字段带 <script> 不原样回显)
    evil = "<script>alert(1)</script>"
    async with TestClient(TestServer(make_app(db))) as client:
        r = await client.post("/login", data={"username": evil, "password": evil, "next": evil},
                              allow_redirects=False)
        assert r.status == 401
        body = (await r.text()).lower()
        assert "<script" not in body and "alert(1)" not in body
        r = await client.get("/login", params={"next": evil})
        body = (await r.text()).lower()
        assert "<script" not in body


@pytest.mark.parametrize("target", ["https://evil.example/x", "//evil.example/x", "/\\evil.example"])
async def test_login_next_open_redirect_blocked(db, target):
    # risk: high  (A2: 开放重定向)
    async with TestClient(TestServer(make_app(db))) as client:
        r = await post_login(client, PWD, next=target)
        assert r.status == 302
        assert r.headers["Location"] == "/dashboard/"
        html = await (await client.get("/login", params={"next": target})).text()
        assert "evil" not in html


async def test_dashboard_escapes_device_name(db):
    # risk: high  (A2: 设备名 XSS 载荷必须转义)
    d1 = "test-fix-" + str(uuidlib.uuid4())
    d2 = "test-fix-" + str(uuidlib.uuid4())
    now_ms = int(time.time() * 1000)
    await db.upsert_devices([Device("dingtek", d1, XSS, "DC414", True, {}),
                             Device("gps51", d2, XSS, "GT06", True, {})])
    try:
        await db.insert_telemetry([Telemetry(d1, "volt", now_ms, 3600.0, None, "rest")])
        await db.insert_gps_positions([GpsPosition(d2, now_ms, now_ms, now_ms, 22.5, 114.0, 10000.0, 0, 0.0, 0.0,
                                                   0, 0, None, None, 1, None, None, None, None, "poll", {})])
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            html = await (await client.get("/dashboard/")).text()
            assert d1 in html and d2 in html
            assert "<img" not in html.lower()
            assert "&lt;img" in html
    finally:
        await cleanup(db, d1)
        await cleanup(db, d2)


async def test_start_refuses_without_api_key_too(db):
    # risk: high  (契约 11: 非回环且 API_KEY 为空也拒启)
    cfg = dataclasses.replace(Config.from_env(), dashboard_host="0.0.0.0", dashboard_pwd="pw", api_key="")
    with pytest.raises(SystemExit):
        await WebServer(cfg, db, None, datetime.now(timezone.utc)).start()


async def test_start_with_port_in_use_does_not_raise(db, caplog):
    # risk: high  (W4: 端口被占只记 error，不拖垮采集；stop 安全)
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", 0))
    blocker.listen(1)
    port = blocker.getsockname()[1]
    ws = WebServer(make_cfg(dashboard_port=port), db, None, datetime.now(timezone.utc))
    try:
        with caplog.at_level(logging.ERROR):
            await asyncio.wait_for(ws.start(), 10)
        assert any(rec.levelno >= logging.ERROR for rec in caplog.records)
        await asyncio.wait_for(ws.stop(), 10)
    finally:
        blocker.close()


async def test_stop_before_start_is_safe(db):
    # risk: medium
    await WebServer(make_cfg(), db, None, datetime.now(timezone.utc)).stop()


def _gps_row(dev, now_ms):
    return GpsPosition(dev, now_ms, now_ms, now_ms, 22.5, 114.0, 10000.0, 0, 0.0, 0.0, 0, 0,
                       None, None, 1, None, None, None, None, "poll", {})


async def test_unregistered_gps_device_still_listed_and_on_dashboard(db):
    # risk: high  (W7: 没有 device 行的推送设备也要出现，name 为 None)
    dev = "test-fix-" + str(uuidlib.uuid4())
    now_ms = int(time.time() * 1000)
    try:
        await db.insert_gps_positions([_gps_row(dev, now_ms)])
        rows = [r for r in await db.latest_gps_positions() if r["device_id"] == dev]
        assert len(rows) == 1
        assert rows[0]["name"] is None
        async with TestClient(TestServer(make_app(db))) as client:
            await login(client)
            html = await (await client.get("/dashboard/")).text()
            assert dev in html
    finally:
        await cleanup(db, dev)


async def test_latest_gps_positions_one_row_when_device_in_both_sources(db):
    # risk: high  (W7: 同 device_id 既有 dingtek 行又有 gps51 行，只出一行)
    dev = "test-fix-" + str(uuidlib.uuid4())
    now_ms = int(time.time() * 1000)
    await db.upsert_devices([Device("dingtek", dev, "dual-dt", "DC414", True, {}),
                             Device("gps51", dev, "dual-gps", "GT06", True, {})])
    try:
        await db.insert_gps_positions([_gps_row(dev, now_ms)])
        rows = [r for r in await db.latest_gps_positions() if r["device_id"] == dev]
        assert len(rows) == 1
        assert rows[0]["name"] == "dual-gps"
    finally:
        await cleanup(db, dev)
