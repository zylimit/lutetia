# risk: high
"""Task 9.1：/app/ 托管 web-ui 构建产物。假 dist 放临时目录，内容全是合成文本。
- /app/ 与前端路由回退 index.html；真实资源 200；不存在的资源 404（不回退）
- /app 与 /app/* 带严格 CSP（style-src 'self'，无 unsafe-inline）与 X-Frame-Options DENY
- 运维看板旧路由 CSP 不变
- 产物目录不存在时 /app/ 503（不 500），其余路由照常
"""
import dataclasses
import errno
import secrets as _secrets
from datetime import datetime, timezone
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config
from lutetia.web.app import SECURITY_HEADERS, WebServer
from lutetia.web.spa import SPA_CSP

INDEX = "<!doctype html><title>spa-test-index</title><div id=app></div>"
ASSET = "console.log('spa-test-asset');"


class NoDB:
    """The SPA shell must never touch the database."""

    def __getattr__(self, name):
        raise AssertionError("db touched: " + name)


def _cfg(dist):
    return dataclasses.replace(
        Config.from_env(), dashboard_pwd="t-" + _secrets.token_hex(8), api_key="k-" + _secrets.token_hex(4),
        dashboard_host="127.0.0.1", login_lockout=False, session_secret="s-" + _secrets.token_hex(8), web_ui_dist=dist)


def _fake_dist(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    (dist / "assets" / "x.js").write_text(ASSET, encoding="utf-8")
    (tmp_path / "secret.txt").write_text("outside-dist", encoding="utf-8")
    return dist


def _client(dist):
    app = WebServer(_cfg(dist), NoDB(), datetime.now(timezone.utc)).build_app()
    return TestClient(TestServer(app))


def _assert_strict(r):
    csp = r.headers["Content-Security-Policy"]
    assert csp == SPA_CSP
    assert "style-src 'self'" in csp and "script-src 'self'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "frame-ancestors 'none'" in csp
    assert r.headers["X-Frame-Options"] == "DENY"


async def test_index_route_fallback_and_assets(tmp_path):
    async with _client(_fake_dist(tmp_path)) as c:
        r = await c.get("/app/")
        assert r.status == 200 and await r.text() == INDEX
        _assert_strict(r)
        for route in ("/app/manholes", "/app/manholes/123", "/app/overview?x=1"):
            r = await c.get(route)
            assert r.status == 200 and await r.text() == INDEX, route
            _assert_strict(r)
        r = await c.get("/app/assets/x.js")
        assert r.status == 200 and await r.text() == ASSET
        _assert_strict(r)


async def test_missing_static_resources_are_404_not_index(tmp_path):
    async with _client(_fake_dist(tmp_path)) as c:
        for path in ("/app/assets/nope.js", "/app/assets/sub/route", "/app/favicon.ico", "/app/nope.css"):
            r = await c.get(path)
            body = await r.text()
            assert r.status == 404, path
            assert "spa-test-index" not in body, path
            _assert_strict(r)


async def test_dotted_route_ids_fall_back_to_index(tmp_path):
    """A last segment with a dot but no known static extension (a POI id) is a front-end route."""
    async with _client(_fake_dist(tmp_path)) as c:
        for path in ("/app/manholes/ABC.DEF", "/app/pois/P-1.2"):
            r = await c.get(path)
            assert r.status == 200 and await r.text() == INDEX, path
            _assert_strict(r)


async def test_no_escape_outside_dist(tmp_path):
    dist = _fake_dist(tmp_path)
    (dist / "link.txt").symlink_to(tmp_path / "secret.txt")
    async with _client(dist) as c:
        for path in ("/app/../secret.txt", "/app/%2e%2e/secret.txt", "/app/assets/..%2f..%2fsecret.txt", "/app/link.txt"):
            r = await c.get(path)
            assert r.status == 404, path
            assert "outside-dist" not in await r.text(), path


async def test_overlong_segment_is_never_500(tmp_path, monkeypatch):
    """Python 3.9 / 3.12 raise OSError(ENAMETOOLONG) from Path.is_file(); simulate it so 3.14 also goes red without the guard."""
    real_is_file = Path.is_file

    def is_file(self, *args, **kwargs):
        if any(len(part) > 255 for part in self.parts):
            raise OSError(errno.ENAMETOOLONG, "File name too long", str(self))
        return real_is_file(self, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", is_file)
    long = "a" * 300
    async with _client(_fake_dist(tmp_path)) as c:
        r = await c.get("/app/" + long)
        assert r.status == 200 and await r.text() == INDEX
        r = await c.get("/app/assets/" + long + ".js")
        assert r.status == 404
        _assert_strict(r)


async def test_bare_app_redirects_with_strict_headers(tmp_path):
    async with _client(_fake_dist(tmp_path)) as c:
        r = await c.get("/app", allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/app/"
        _assert_strict(r)


async def test_ops_dashboard_csp_unchanged(tmp_path):
    async with _client(_fake_dist(tmp_path)) as c:
        for path in ("/login", "/dashboard/", "/static/app.css", "/application"):
            r = await c.get(path, allow_redirects=False)
            assert r.headers["Content-Security-Policy"] == SECURITY_HEADERS["Content-Security-Policy"], path
            assert "'unsafe-inline'" in r.headers["Content-Security-Policy"], path


async def test_missing_build_is_503_and_rest_still_serves(tmp_path):
    async with _client(tmp_path / "no-such-dist") as c:
        for path in ("/app/", "/app/manholes", "/app/assets/x.js"):
            r = await c.get(path)
            assert r.status == 503, path
            assert "npm run build" in await r.text()
            _assert_strict(r)
        r = await c.get("/login")
        assert r.status == 200
        assert r.headers["Content-Security-Policy"] == SECURITY_HEADERS["Content-Security-Policy"]
