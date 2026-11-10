# risk: high
"""Task 9.2: sign-in for the project dashboard SPA (/app/signin posts to /login) and GET /api/v1/me.
- next under /app/ is followed after login; every open-redirect spelling falls back to the ops default page
- a failed login that came from the SPA goes back to /app/signin?error=1; any other failed login behaves as before
- /api/v1/me: session -> account name, key -> caller name, nothing -> 401
- /logout?next=/app/signin lands on the SPA sign-in, any other next is ignored
Passwords are random per run (monkeypatched into Config), never real values; no database is touched."""
import dataclasses
import hashlib
import json
import secrets
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from aiohttp import DummyCookieJar
from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config
from lutetia.web.app import WebServer
from lutetia.web.auth import safe_app_next

DEFAULT_PAGE = "/dashboard/"
PWD = {"admin": "t-" + secrets.token_hex(6), "orange": "t-" + secrets.token_hex(6), "huawei": "t-" + secrets.token_hex(6)}
LEGACY_KEY = "k-" + secrets.token_hex(8)
NAMED_KEY = "k-" + secrets.token_hex(8)


class NoDB:
    def __getattr__(self, name):
        raise AssertionError("db touched: " + name)


def make_client(tmp_path, lockout=False):
    callers = tmp_path / "callers.json"
    callers.write_text(json.dumps([{"name": "caller-named", "key_sha256": hashlib.sha256(NAMED_KEY.encode()).hexdigest(),
                                    "scopes": ["poi:read"], "origins": [], "rate_per_min": 100000}]), encoding="utf-8")
    cfg = dataclasses.replace(
        Config.from_env(), dashboard_pwd=PWD["admin"], orange_pwd=PWD["orange"], huawei_pwd=PWD["huawei"], api_key=LEGACY_KEY,
        callers_file=str(callers), dashboard_host="127.0.0.1", login_lockout=lockout, session_secret="s-" + secrets.token_hex(8),
        legacy_rate_per_min=100000, session_rate_per_min=100000)
    app = WebServer(cfg, NoDB(), datetime.now(timezone.utc)).build_app()
    return TestClient(TestServer(app), cookie_jar=DummyCookieJar())


async def post_login(c, user="orange", password=None, next_url="", remember=True):
    data = {"username": user, "password": PWD[user] if password is None else password, "next": next_url}
    if remember:
        data["remember"] = "1"
    return await c.post("/login", data=data, allow_redirects=False)


def session_header(resp):
    return {"Cookie": "lutetia_session=" + resp.cookies["lutetia_session"].value}


# ---- safe_app_next (pure) ---------------------------------------------------------------------------------------------------

VALID_NEXT = ["/app/", "/app/manholes", "/app/manholes?status=moved&range=7d", "/app/pois/ABC.DEF", "/app/signin?next=%2Fapp%2Fplan"]
EVIL_NEXT = [
    "//evil.example/app/", "/\\evil.example", "/app/\\evil.example", "/app//evil.example", "/app/%2f%2fevil.example",
    "/app/%2F%2Fevil.example", "/app/%5cevil.example", "/app/%252f%252fevil.example", "https://evil.example/app/",
    "http://evil.example", "javascript:alert(1)", "/app/../dashboard/", "/app/%2e%2e/%2e%2e/", "/app/./x", "/app/x\r\nSet-Cookie: a=b",
    "/app/\t//evil.example", "/app/x\x00", "/app/\x7f", "/app", "/app\\", "app/", "/app/" + "a" * 600, "",
]


@pytest.mark.parametrize("target", VALID_NEXT)
def test_safe_app_next_accepts_plain_app_paths(target):
    assert safe_app_next(target) == target


@pytest.mark.parametrize("target", EVIL_NEXT)
def test_safe_app_next_refuses_every_open_redirect_spelling(target):
    assert safe_app_next(target) is None


# ---- /login with next ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("user", ["orange", "huawei", "admin"])
@pytest.mark.parametrize("target", VALID_NEXT[:4])
async def test_login_follows_app_next_for_every_account(tmp_path, user, target):
    async with make_client(tmp_path) as c:
        r = await post_login(c, user, next_url=target)
        assert r.status == 302 and r.headers["Location"] == target
        assert "lutetia_session" in r.cookies


async def test_remember_sets_thirty_days_and_unchecked_sets_twelve_hours(tmp_path):
    async with make_client(tmp_path) as c:
        r = await post_login(c, next_url="/app/", remember=True)
        assert int(r.cookies["lutetia_session"]["max-age"]) == 2592000
        r = await post_login(c, next_url="/app/", remember=False)
        assert int(r.cookies["lutetia_session"]["max-age"]) == 43200


@pytest.mark.parametrize("target", [t for t in EVIL_NEXT if t])
async def test_login_with_unsafe_next_goes_to_the_default_page(tmp_path, target):
    async with make_client(tmp_path) as c:
        r = await post_login(c, next_url=target)
        assert r.status == 302 and r.headers["Location"] == DEFAULT_PAGE, target
        assert "lutetia_session" in r.cookies  # the login itself still succeeded


async def test_login_without_next_and_ops_next_unchanged(tmp_path):
    async with make_client(tmp_path) as c:
        assert (await post_login(c, next_url="")).headers["Location"] == DEFAULT_PAGE
        assert (await post_login(c, next_url="/dashboard/map")).headers["Location"] == "/dashboard/map"
        assert (await post_login(c, next_url="//evil.example")).headers["Location"] == DEFAULT_PAGE


# ---- failed login ----------------------------------------------------------------------------------------------------------

async def test_failed_login_from_the_spa_returns_to_the_spa_sign_in(tmp_path):
    async with make_client(tmp_path) as c:
        r = await post_login(c, "orange", password="wrong-" + secrets.token_hex(4), next_url="/app/manholes?status=moved")
        assert r.status == 303
        loc = urlsplit(r.headers["Location"])
        assert loc.path == "/app/signin"
        q = parse_qs(loc.query)
        assert q["error"] == ["1"] and q["next"] == ["/app/manholes?status=moved"]
        assert "lutetia_session" not in r.cookies
        r = await post_login(c, "orange", password="", next_url="/app/")  # empty password is wrong too
        assert r.status == 303 and "error=1" in r.headers["Location"]


async def test_failed_login_keeps_a_next_that_already_carries_error_params(tmp_path):
    async with make_client(tmp_path) as c:
        target = "/app/x?a=1&error=locked"
        r = await post_login(c, "orange", password="wrong-" + secrets.token_hex(4), next_url=target)
        assert r.status == 303
        q = parse_qs(urlsplit(r.headers["Location"]).query)
        assert q["next"] == [target] and q["error"] == ["1"]  # the original next is returned whole, our own error is the only error


async def test_failed_login_not_from_the_spa_keeps_the_old_page(tmp_path):
    async with make_client(tmp_path) as c:
        for target in ("", "/dashboard/", "//evil.example", "/app//evil.example"):  # the last: unsafe /app target is not treated as the SPA
            r = await post_login(c, "orange", password="wrong-" + secrets.token_hex(4), next_url=target)
            assert r.status == 401 and "Location" not in r.headers, target
            assert "账号或密码错误" in await r.text()


async def test_locked_login_from_the_spa_goes_back_with_error_locked(tmp_path):
    async with make_client(tmp_path, lockout=True) as c:
        for _ in range(5):
            await post_login(c, "orange", password="wrong-" + secrets.token_hex(4), next_url="/app/")
        r = await post_login(c, "orange", next_url="/app/")  # even the right password is refused while locked
        assert r.status == 303 and "error=locked" in r.headers["Location"]
        r = await post_login(c, "orange", next_url="")
        assert r.status == 429


# ---- /api/v1/me ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("user", ["orange", "huawei", "admin"])
async def test_me_with_a_session_returns_the_account_name(tmp_path, user):
    async with make_client(tmp_path) as c:
        headers = session_header(await post_login(c, user))
        r = await c.get("/api/v1/me", headers=headers)
        body = await r.json()
        assert r.status == 200 and body["data"] == {"account": user}
        assert set(body) == {"data", "as_of"} and body["as_of"].endswith("Z")


async def test_me_with_a_key_returns_the_caller_name(tmp_path):
    async with make_client(tmp_path) as c:
        r = await c.get("/api/v1/me", headers={"Authorization": "Bearer " + NAMED_KEY})  # a key with only poi:read still passes
        assert r.status == 200 and (await r.json())["data"] == {"account": "caller-named"}
        r = await c.get("/api/v1/me", headers={"Authorization": "Bearer " + LEGACY_KEY})
        assert r.status == 200 and (await r.json())["data"] == {"account": "legacy"}


async def test_me_without_a_valid_credential_is_401(tmp_path):
    async with make_client(tmp_path) as c:
        r = await c.get("/api/v1/me")
        assert r.status == 401 and r.headers["WWW-Authenticate"] == "Bearer"
        assert (await c.get("/api/v1/me", headers={"Authorization": "Bearer nope"})).status == 401
        assert (await c.get("/api/v1/me", headers={"Cookie": "lutetia_session=garbage"})).status == 401
        assert (await c.post("/api/v1/me")).status in (404, 405)  # read-only


async def test_me_is_401_again_after_logout(tmp_path):
    async with make_client(tmp_path) as c:
        headers = session_header(await post_login(c, "orange"))
        assert (await c.get("/api/v1/me", headers=headers)).status == 200
        await c.get("/logout", headers=headers, allow_redirects=False)
        assert (await c.get("/api/v1/me", headers=headers)).status == 401


# ---- /logout ---------------------------------------------------------------------------------------------------------------

async def test_logout_lands_on_the_spa_sign_in_only_for_a_safe_app_next(tmp_path):
    async with make_client(tmp_path) as c:
        headers = session_header(await post_login(c, "orange"))
        r = await c.get("/logout?next=/app/signin", headers=headers, allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/app/signin"
        assert r.cookies["lutetia_session"].value == ""  # cookie cleared
        for target in ("//evil.example", "https://evil.example", "/app//x", "/dashboard/", ""):
            r = await c.get("/logout", params={"next": target}, headers=headers, allow_redirects=False)
            assert r.status == 302 and r.headers["Location"] == "/login", target
        assert (await c.get("/logout", allow_redirects=False)).headers["Location"] == "/login"


# ---- the ops dashboard is still admin only ---------------------------------------------------------------------------------

async def test_a_non_admin_account_still_gets_the_coming_soon_line_on_the_ops_dashboard(tmp_path):
    async with make_client(tmp_path) as c:
        headers = session_header(await post_login(c, "orange", next_url="/app/"))
        r = await c.get("/dashboard/", headers=headers)
        assert r.status == 200 and 'id="coming-soon"' in await r.text()


# ---- POST /logout (same-origin only) and the site root --------------------------------------------------------------------

async def test_post_logout_same_origin_revokes_and_lands_on_the_spa_sign_in(tmp_path):
    async with make_client(tmp_path) as c:
        headers = session_header(await post_login(c, "orange"))
        origin = "http://%s:%s" % (c.server.host, c.server.port)
        r = await c.post("/logout", data={"next": "/app/signin"}, headers={**headers, "Origin": origin}, allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/app/signin"
        assert r.cookies["lutetia_session"].value == ""
        assert (await c.get("/api/v1/me", headers=headers)).status == 401


async def test_post_logout_accepts_a_same_origin_referer_when_origin_is_missing_and_ignores_an_unsafe_next(tmp_path):
    async with make_client(tmp_path) as c:
        headers = session_header(await post_login(c, "orange"))
        referer = "http://%s:%s/app/" % (c.server.host, c.server.port)
        r = await c.post("/logout", data={"next": "//evil.example"}, headers={**headers, "Referer": referer}, allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/login"
        assert (await c.get("/api/v1/me", headers=headers)).status == 401


@pytest.mark.parametrize("hdrs", [{"Origin": "https://evil.example"}, {"Origin": "null"}, {"Referer": "https://evil.example/app/"}, {}])
async def test_post_logout_cross_site_or_unsourced_is_403_and_the_session_survives(tmp_path, hdrs):
    async with make_client(tmp_path) as c:
        headers = session_header(await post_login(c, "orange"))
        r = await c.post("/logout", data={"next": "/app/signin"}, headers={**headers, **hdrs}, allow_redirects=False)
        assert r.status == 403 and "lutetia_session" not in r.cookies
        assert (await c.get("/api/v1/me", headers=headers)).status == 200  # still signed in


async def test_get_logout_is_unchanged_for_the_ops_dashboard_link(tmp_path):
    async with make_client(tmp_path) as c:
        headers = session_header(await post_login(c, "admin"))
        r = await c.get("/logout", headers=headers, allow_redirects=False)  # no Origin / Referer: GET needs neither
        assert r.status == 302 and r.headers["Location"] == "/login"
        assert (await c.get("/api/v1/me", headers=headers)).status == 401


async def test_site_root_sends_admin_to_the_ops_dashboard_and_everyone_else_to_the_project_dashboard(tmp_path):
    async with make_client(tmp_path) as c:
        r = await c.get("/", allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == "/app/"  # signed out: the SPA sends it to /app/signin
        r = await c.get("/", headers={"Cookie": "lutetia_session=garbage"}, allow_redirects=False)
        assert r.headers["Location"] == "/app/"
        for user in ("orange", "huawei"):
            r = await c.get("/", headers=session_header(await post_login(c, user)), allow_redirects=False)
            assert r.status == 302 and r.headers["Location"] == "/app/", user
        r = await c.get("/", headers=session_header(await post_login(c, "admin")), allow_redirects=False)
        assert r.status == 302 and r.headers["Location"] == DEFAULT_PAGE


async def test_the_coming_soon_page_links_to_the_project_dashboard(tmp_path):
    async with make_client(tmp_path) as c:
        r = await c.get("/dashboard/", headers=session_header(await post_login(c, "orange", next_url="/app/")))
        html = await r.text()
        assert 'id="coming-soon"' in html and '<a href="/app/">Open the project dashboard</a>' in html
