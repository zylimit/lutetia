# risk: high
"""Task 8.1：运维看板只许 admin。路由清单取自 app.router（新增 /dashboard 路由自动被测到）。
- 未登录：页面 302 -> /login?next=<原路径>，/dashboard/data/* 401
- orange / huawei：页面 200 + 提示一句，数据口 403，假库被碰 0 次
- admin：至少一条路由碰了假库（证明计数器有效）
"""
import dataclasses
import re
import secrets as _secrets
from datetime import datetime, timezone
from urllib.parse import quote

import pytest
from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config
from lutetia.web.app import WebServer

NOTICE = "The project dashboard is coming soon."


class CountingDB:
    """Any attribute access (hence any method call) is counted; calls return None-ish awaitables."""

    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)

        async def _noop(*a, **k):
            return []
        return _noop


def _pw():
    return "t-" + _secrets.token_hex(8)


def _cfg():
    return dataclasses.replace(
        Config.from_env(), dashboard_pwd=_pw(), orange_pwd=_pw(), huawei_pwd=_pw(), api_key="k-" + _secrets.token_hex(4),
        dashboard_host="127.0.0.1", login_lockout=False, session_secret="s-" + _secrets.token_hex(8))


def _build(cfg, db):
    return WebServer(cfg, db, datetime.now(timezone.utc)).build_app()


def _dashboard_paths(app):
    """(page_paths, data_paths) from the live router; dynamic segments filled with a placeholder."""
    pages, data = [], []
    for res in app.router.resources():
        canon = res.canonical
        if not (canon == "/dashboard" or canon.startswith("/dashboard/")):
            continue
        if not any(r.method in ("GET", "*") for r in res):
            continue
        path = re.sub(r"\{[^}]+\}", "x", canon)
        (data if path.startswith("/dashboard/data/") else pages).append(path)
    return sorted(pages), sorted(data)


async def _login(client, user, pwd):
    r = await client.post("/login", data={"username": user, "password": pwd, "next": ""}, allow_redirects=False)
    assert r.status == 302, user
    return {"Cookie": "lutetia_session=" + r.cookies["lutetia_session"].value}


def test_router_enumeration_is_not_empty():
    pages, data = _dashboard_paths(_build(_cfg(), CountingDB()))
    assert len(pages) >= 3 and len(data) >= 4
    assert "/dashboard/" in pages and "/dashboard/map" in pages


async def test_anonymous_pages_redirect_and_data_401():
    cfg, db = _cfg(), CountingDB()
    app = _build(cfg, db)
    pages, data = _dashboard_paths(app)
    async with TestClient(TestServer(app)) as c:
        for p in pages:
            r = await c.get(p, allow_redirects=False)
            assert r.status == 302, p
            assert r.headers["Location"] == "/login?next=" + quote(p), p
        for p in data:
            r = await c.get(p, allow_redirects=False)
            assert r.status == 401, p
    assert db.touched == []


@pytest.mark.parametrize("user,field", [("orange", "orange_pwd"), ("huawei", "huawei_pwd")])
async def test_non_admin_sees_notice_only_and_never_touches_db(user, field):
    cfg, db = _cfg(), CountingDB()
    app = _build(cfg, db)
    pages, data = _dashboard_paths(app)
    async with TestClient(TestServer(app)) as c:
        hdr = await _login(c, user, getattr(cfg, field))
        for p in pages:
            r = await c.get(p, headers=hdr, allow_redirects=False)
            body = await r.text()
            assert r.status == 200 and NOTICE in body, p
        for p in data:
            r = await c.get(p, headers=hdr, allow_redirects=False)
            assert r.status == 403, p
    assert db.touched == [], db.touched


async def test_admin_reaches_db_so_counter_is_proven_live():
    cfg, db = _cfg(), CountingDB()
    app = _build(cfg, db)
    pages, data = _dashboard_paths(app)
    async with TestClient(TestServer(app)) as c:
        hdr = await _login(c, "admin", cfg.dashboard_pwd)
        for p in pages + data:
            r = await c.get(p, headers=hdr, allow_redirects=False)
            assert r.status != 403, p
            assert NOTICE not in await r.text(), p
    assert db.touched, "admin hit no route that touches the db: counter proves nothing"
