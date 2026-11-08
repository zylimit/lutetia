# risk: high
"""Task 2.4 contract 1-5: session signer, login limiter, password check (pure functions, no DB)."""
import pytest

from lutetia.web.auth import LoginLimiter, SessionSigner, check_password

SECRET = b"unit-test-secret-0123456789abcdef"
ACCTS = {"admin": "pw-admin-unit"}


def test_session_roundtrip():
    s = SessionSigner(SECRET, ACCTS)
    token = s.issue("admin", now=1000.0)
    assert s.verify(token, now=1001.0) == "admin"
    # a different secret must not accept it
    assert SessionSigner(b"another-secret-xxxxxxxxxxxxxxxxx", ACCTS).verify(token, now=1001.0) is None


def test_session_tampered_is_rejected():
    s = SessionSigner(SECRET, ACCTS)
    token = s.issue("admin", now=1000.0)
    payload, sig = token.split(".")
    assert s.verify(token, now=1001.0) == "admin"
    # flip each position of payload and of signature
    for i in range(len(payload)):
        c = "A" if payload[i] != "A" else "B"
        assert s.verify(payload[:i] + c + payload[i + 1:] + "." + sig, now=1001.0) is None
    for i in range(len(sig)):
        c = "0" if sig[i] != "0" else "1"
        assert s.verify(payload + "." + sig[:i] + c + sig[i + 1:], now=1001.0) is None
    for bad in ("", "garbage", ".", "a.b.c", payload, payload + "."):
        assert s.verify(bad, now=1001.0) is None


def test_session_expired_is_rejected():
    s = SessionSigner(SECRET, ACCTS, ttl_seconds=100)
    token = s.issue("admin", now=1000.0)
    assert s.verify(token, now=1099.0) == "admin"
    assert s.verify(token, now=1101.0) is None
    assert s.verify(token, now=1000.0 + 10 ** 6) is None


def test_login_limiter_locks_after_five_failures():
    lim = LoginLimiter(max_failures=5, lock_seconds=300)
    t = 5000.0
    for _ in range(4):
        lim.record_failure("1.2.3.4", now=t)
    assert lim.is_locked("1.2.3.4", now=t) is False
    lim.record_failure("1.2.3.4", now=t)
    assert lim.is_locked("1.2.3.4", now=t) is True
    assert lim.is_locked("1.2.3.4", now=t + 299) is True
    assert lim.is_locked("1.2.3.4", now=t + 301) is False
    # other ip unaffected
    assert lim.is_locked("9.9.9.9", now=t) is False
    # reset unlocks immediately
    lim2 = LoginLimiter()
    for _ in range(5):
        lim2.record_failure("5.5.5.5", now=t)
    assert lim2.is_locked("5.5.5.5", now=t) is True
    lim2.reset("5.5.5.5")
    assert lim2.is_locked("5.5.5.5", now=t) is False


@pytest.mark.parametrize("given,expected,ok", [
    ("pw", "pw", True),
    ("pw", "other", False),
    ("", "pw", False),
    ("", "", False),
    ("anything", "", False),
])
def test_check_password(given, expected, ok):
    assert check_password(given, expected) is ok


# ---- 审查修复 W1：client_ip 信任边界 + 全局兜底 + limiter 淘汰（红锁） ----
from types import SimpleNamespace  # noqa: E402

from lutetia.config import Config  # noqa: E402
from lutetia.web.auth import client_ip  # noqa: E402


def _req(remote, xff=None):
    headers = {}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    return SimpleNamespace(remote=remote, headers=headers)


def test_client_ip_ignores_xff_when_not_trusted():
    # risk: high
    assert client_ip(_req("198.51.100.7", "1.1.1.1"), False) == "198.51.100.7"
    assert client_ip(_req("127.0.0.1", "203.0.113.5"), False) == "127.0.0.1"


@pytest.mark.parametrize("remote", ["127.0.0.1", "10.1.2.3", "172.16.0.9", "172.31.255.1", "192.168.1.20", "::1"])
def test_client_ip_trusts_xff_from_loopback_or_private_remote(remote):
    # risk: high
    assert client_ip(_req(remote, "203.0.113.5"), True) == "203.0.113.5"


@pytest.mark.parametrize("remote", ["8.8.8.8", "198.51.100.7", "172.32.0.1", "2001:db8::1"])
def test_client_ip_ignores_xff_from_public_remote_even_if_trusted(remote):
    # risk: high
    assert client_ip(_req(remote, "203.0.113.5"), True) == remote


def test_client_ip_trusted_without_xff_falls_back_to_remote():
    # risk: medium
    assert client_ip(_req("127.0.0.1"), True) == "127.0.0.1"
    assert client_ip(_req("127.0.0.1", "  "), True) == "127.0.0.1"


@pytest.mark.parametrize("raw,expected", [("1", True), ("true", True), ("yes", True), ("false", False), ("0", False)])
def test_config_trust_proxy_env(monkeypatch, raw, expected):
    # risk: medium
    monkeypatch.setenv("DASHBOARD_TRUST_PROXY", raw)
    assert Config.from_env().trust_proxy is expected


def test_config_trust_proxy_default_false(monkeypatch):
    # risk: medium
    monkeypatch.delenv("DASHBOARD_TRUST_PROXY", raising=False)
    assert Config.from_env().trust_proxy is False


def test_limiter_global_lock_after_fifty_failures_from_many_ips():
    # risk: high
    lim = LoginLimiter()
    t = 10000.0
    for i in range(49):
        lim.record_failure("10.9.%d.%d" % (i // 200, i % 200), now=t)
    assert lim.is_globally_locked(now=t) is False
    lim.record_failure("10.9.9.9", now=t)
    assert lim.is_globally_locked(now=t) is True
    assert lim.is_globally_locked(now=t + 59) is True
    assert lim.is_globally_locked(now=t + 61) is False


def test_limiter_global_window_forgets_old_failures():
    # risk: medium
    lim = LoginLimiter()
    t = 20000.0
    for i in range(49):
        lim.record_failure("172.20.0.%d" % i, now=t)
    lim.record_failure("172.20.1.1", now=t + 301)  # earlier 49 fell out of the 300s window
    assert lim.is_globally_locked(now=t + 301) is False


def test_limiter_evicts_stale_entries():
    # risk: high
    lim = LoginLimiter()
    t = 30000.0
    for i in range(200):
        lim.record_failure("192.0.2.%d.%d" % (i // 250, i % 250), now=t)
    lim.record_failure("198.51.100.1", now=t + 1000)
    assert len(lim._failures) <= 2
    assert len(lim._locked_until) <= 2


def test_limiter_evicts_stale_locks():
    # risk: high
    lim = LoginLimiter()
    t = 40000.0
    for i in range(50):
        for _ in range(5):
            lim.record_failure("ip-%d" % i, now=t)
    lim.record_failure("fresh", now=t + 1000)
    assert len(lim._locked_until) <= 2
    assert len(lim._failures) <= 2


def test_limiter_entries_capped_at_ten_thousand():
    # risk: medium
    lim = LoginLimiter()
    t = 50000.0
    for i in range(10500):
        lim.record_failure("ip-%d" % i, now=t + i * 0.001)
    assert len(lim._failures) <= 10000


def test_session_two_tokens_same_second_differ_and_revoke_is_independent():
    # risk: high  (W8: 同一 now 签的两枚 token 不同；撤销一枚不连坐另一枚)
    s = SessionSigner(SECRET, ACCTS)
    a = s.issue("admin", now=1000.0)
    b = s.issue("admin", now=1000.0)
    assert a != b
    s.revoke(a, now=1001.0)
    assert s.verify(a, now=1002.0) is None
    assert s.verify(b, now=1002.0) == "admin"


def test_client_ip_takes_last_xff_value_when_trusted():
    # risk: high  (W9: 取受信代理追加的最后一个值，前面的由客户端伪造)
    assert client_ip(_req("127.0.0.1", "1.1.1.1, 203.0.113.5"), True) == "203.0.113.5"
    assert client_ip(_req("127.0.0.1", "203.0.113.5"), True) == "203.0.113.5"


# ---- v1.10 DASHBOARD_LOGIN_LOCKOUT：测试阶段可关登录锁定，默认仍开（红锁） ----
import dataclasses  # noqa: E402
import logging  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from lutetia.web import WebServer  # noqa: E402

_LOCK_PWD = "pw-test"


@pytest.mark.parametrize("raw", ["off", "0", "false", "no", " OFF ", "False", "NO"])
def test_config_login_lockout_off_values(monkeypatch, raw):
    # risk: high
    monkeypatch.setenv("DASHBOARD_LOGIN_LOCKOUT", raw)
    assert Config.from_env().login_lockout is False


@pytest.mark.parametrize("raw", ["", "  ", "on", "1", "true", "yes", "garbage"])
def test_config_login_lockout_on_values(monkeypatch, raw):
    # risk: high  (空 / 其它值一律保持开启，防误关)
    monkeypatch.setenv("DASHBOARD_LOGIN_LOCKOUT", raw)
    assert Config.from_env().login_lockout is True


def test_config_login_lockout_default_on(monkeypatch):
    # risk: high
    monkeypatch.delenv("DASHBOARD_LOGIN_LOCKOUT", raising=False)
    assert Config.from_env().login_lockout is True


def test_limiter_disabled_never_locks():
    # risk: high
    lim = LoginLimiter(enabled=False)
    t = 60000.0
    for i in range(200):
        lim.record_failure("1.2.3.4", now=t)
        lim.record_failure("10.0.%d.%d" % (i // 200, i % 200), now=t)
    assert lim.is_locked("1.2.3.4", now=t) is False
    assert lim.is_globally_locked(now=t) is False


def _lock_app(lockout):
    cfg = dataclasses.replace(Config.from_env(), dashboard_pwd=_LOCK_PWD, api_key="k-test",
                              dashboard_host="127.0.0.1", login_lockout=lockout)
    return WebServer(cfg, None, datetime.now(timezone.utc)).build_app()


async def _post_login(client, password):
    return await client.post("/login", data={"username": "admin", "password": password, "next": ""},
                             allow_redirects=False)


async def test_login_lockout_disabled_correct_password_still_works_after_six_failures(caplog):
    # risk: high
    caplog.set_level(logging.WARNING)
    async with TestClient(TestServer(_lock_app(False))) as client:
        for _ in range(6):
            assert (await _post_login(client, "wrong")).status == 401
        r = await _post_login(client, _LOCK_PWD)
        assert r.status == 302
        assert "lutetia_session" in r.cookies
    failed = [rec for rec in caplog.records if "web login: failed attempt" in rec.getMessage()]
    assert len(failed) == 6
    assert not [rec for rec in caplog.records if "locked" in rec.getMessage()]


async def test_login_lockout_enabled_rejects_correct_password_after_failures():
    # risk: high
    async with TestClient(TestServer(_lock_app(True))) as client:
        for _ in range(5):
            assert (await _post_login(client, "wrong")).status == 401
        assert (await _post_login(client, "wrong")).status == 429
        r = await _post_login(client, _LOCK_PWD)
        assert r.status == 429
        assert "lutetia_session" not in r.cookies


@pytest.mark.parametrize("enabled", [False, True])
def test_limiter_recent_list_is_bounded_under_sustained_failures(enabled):
    # risk: high
    # 单 IP 持续猜密码（含锁定关闭、直接绕过 is_locked）时全局失败列表不得无限增长，否则占满事件循环
    lim = LoginLimiter(enabled=enabled)
    for _ in range(1000):
        lim.record_failure("203.0.113.9", now=5000.0)
    assert len(lim._recent) <= lim.global_max_failures
    # 时间递增但都在窗口内，同样有界
    lim2 = LoginLimiter(enabled=enabled)
    for i in range(1000):
        lim2.record_failure("203.0.113.9", now=5000.0 + i * 0.1)
    assert 1000 * 0.1 < lim2.global_window_seconds
    assert len(lim2._recent) <= lim2.global_max_failures


def test_limiter_global_lock_still_triggers_when_recent_is_bounded():
    # risk: high
    lim = LoginLimiter()
    for _ in range(50):
        lim.record_failure("203.0.113.9", now=7000.0)
    assert lim.is_globally_locked(7000.0) is True


# ---- Phase 8 Task 8.1：三个账号、30 天会话、按账号派生签名密钥（红锁）----
import secrets as _secrets  # noqa: E402
import os as _os  # noqa: E402

from lutetia.db import Database  # noqa: E402
from lutetia.web.auth import authenticate  # noqa: E402

_DB_URL = _os.environ.get("DATABASE_URL", "")


@pytest.fixture
async def db():
    if not _DB_URL:
        pytest.skip("DATABASE_URL not set")
    d = Database(_DB_URL)
    try:
        await d.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip("database unreachable: %s" % e)
    yield d
    await d.close()


def _pw():
    return "t-" + _secrets.token_hex(8)  # runtime-random, never hard-coded


def _acct_cfg(**kw):
    base = dict(dashboard_pwd=_pw(), orange_pwd=_pw(), huawei_pwd=_pw(), api_key="k-test",
                dashboard_host="127.0.0.1", login_lockout=False, session_secret="s-" + _secrets.token_hex(8))
    base.update(kw)
    return dataclasses.replace(Config.from_env(), **base)


def _acct_app(cfg, db=None):
    return WebServer(cfg, db, datetime.now(timezone.utc)).build_app()


async def _login_as(client, user, pwd, remember=False):
    data = {"username": user, "password": pwd, "next": ""}
    if remember:
        data["remember"] = "1"
    return await client.post("/login", data=data, allow_redirects=False)


def _cookie(resp):
    return {"Cookie": "lutetia_session=" + resp.cookies["lutetia_session"].value}


async def test_three_accounts_can_log_in():
    # risk: high
    cfg = _acct_cfg()
    async with TestClient(TestServer(_acct_app(cfg))) as c:
        for user, pwd in (("admin", cfg.dashboard_pwd), ("orange", cfg.orange_pwd), ("huawei", cfg.huawei_pwd)):
            r = await _login_as(c, user, pwd)
            assert r.status == 302 and "lutetia_session" in r.cookies, user


async def test_wrong_password_and_cross_account_password_fail():
    # risk: high
    cfg = _acct_cfg()
    async with TestClient(TestServer(_acct_app(cfg))) as c:
        assert (await _login_as(c, "orange", _pw())).status == 401
        assert (await _login_as(c, "orange", cfg.huawei_pwd)).status == 401  # another account's password
        assert (await _login_as(c, "nobody", cfg.orange_pwd)).status == 401


async def test_account_without_password_is_not_enabled():
    # risk: high
    cfg = _acct_cfg(orange_pwd="")
    assert sorted(cfg.accounts()) == ["admin", "huawei"]
    async with TestClient(TestServer(_acct_app(cfg))) as c:
        assert (await _login_as(c, "orange", "")).status == 401
        assert (await _login_as(c, "orange", "anything")).status == 401
        assert (await _login_as(c, "huawei", cfg.huawei_pwd)).status == 302


def test_authenticate_checks_every_account_without_early_return(monkeypatch):
    # risk: high  (用户名不匹配也要把每个账号的密码都比一遍，响应时间不区分「用户名对不对」)
    import lutetia.web.auth as auth
    calls = []
    real = auth.check_password
    monkeypatch.setattr(auth, "check_password", lambda g, e: (calls.append(e), real(g, e))[1])
    accts = {"a": "pa", "b": "pb", "c": "pc"}
    assert authenticate(accts, "zzz", "pa") is None
    assert calls == ["pa", "pb", "pc"]
    calls.clear()
    assert authenticate(accts, "a", "pa") == "a"
    assert calls == ["pa", "pb", "pc"]
    assert authenticate(accts, "a", "pb") is None  # right name, another account's password


async def test_password_change_kills_only_that_accounts_sessions():
    # risk: high
    cfg = _acct_cfg()
    async with TestClient(TestServer(_acct_app(cfg))) as c:
        tokens = {u: _cookie(await _login_as(c, u, p)) for u, p in
                  (("admin", cfg.dashboard_pwd), ("orange", cfg.orange_pwd), ("huawei", cfg.huawei_pwd))}
    cfg2 = dataclasses.replace(cfg, orange_pwd=_pw())
    # exercise both guards through a tiny app sharing the real signer
    from aiohttp import web as _web
    from lutetia.web.auth import require_session, require_session_json

    async def ok(request):
        return _web.json_response({"user": request["user"]})

    for label, c_cfg in (("same", cfg), ("changed", cfg2)):
        app = _acct_app(c_cfg)
        app.router.add_get("/probe-json", require_session_json(ok))
        app.router.add_get("/probe-page", require_session(ok))
        async with TestClient(TestServer(app)) as c3:
            for user, hdr in tokens.items():
                rj = await c3.get("/probe-json", headers=hdr, allow_redirects=False)
                rp = await c3.get("/probe-page", headers=hdr, allow_redirects=False)
                if label == "changed" and user == "orange":
                    assert rj.status == 401
                    assert rp.status == 302 and rp.headers["Location"].startswith("/login")
                else:
                    assert rj.status == 200 and (await rj.json())["user"] == user
                    assert rp.status == 200


async def test_session_secret_change_kills_all_sessions():
    # risk: high
    cfg = _acct_cfg()
    async with TestClient(TestServer(_acct_app(cfg))) as c:
        tokens = [_cookie(await _login_as(c, u, p)) for u, p in
                  (("admin", cfg.dashboard_pwd), ("orange", cfg.orange_pwd), ("huawei", cfg.huawei_pwd))]
    cfg2 = dataclasses.replace(cfg, session_secret="s-" + _secrets.token_hex(8))
    from aiohttp import web as _web
    from lutetia.web.auth import require_session_json

    async def ok(request):
        return _web.json_response({})

    for c_cfg, expect in ((cfg, 200), (cfg2, 401)):
        app = _acct_app(c_cfg)
        app.router.add_get("/probe-json", require_session_json(ok))
        async with TestClient(TestServer(app)) as c3:
            for hdr in tokens:
                assert (await c3.get("/probe-json", headers=hdr)).status == expect


def test_disabled_account_token_is_rejected():
    # risk: high  (账号密码被删后，它此前签发的 cookie 立即无效)
    pw = _pw()
    s1 = SessionSigner(SECRET, {"admin": _pw(), "orange": pw})
    token = s1.issue("orange", now=1000.0)
    assert s1.verify(token, now=1001.0) == "orange"
    s2 = SessionSigner(SECRET, {"admin": _pw()})
    assert s2.verify(token, now=1001.0) is None


def test_signing_key_is_derived_per_account_and_old_format_rejected():
    # risk: high
    import hmac as _hmac, hashlib as _hashlib, json as _json
    from lutetia.web.auth import _b64e
    pw = _pw()
    s = SessionSigner(SECRET, {"admin": pw})
    # a token signed with the pre-v2 scheme (key = secret only) must not verify
    payload = _b64e(_json.dumps({"u": "admin", "iat": 1000, "n": "00", "exp": 2000}).encode())
    old = payload + "." + _hmac.new(SECRET, payload.encode(), _hashlib.sha256).hexdigest()
    assert s.verify(old, now=1001.0) is None
    # a token signed with exactly the documented derivation does verify
    key = _hmac.new(SECRET, ("lutetia-session-v2|admin|" + pw).encode(), _hashlib.sha256).digest()
    good = payload + "." + _hmac.new(key, payload.encode(), _hashlib.sha256).hexdigest()
    assert s.verify(good, now=1001.0) == "admin"


def test_issue_ttl_remember_vs_default():
    # risk: high
    s = SessionSigner(SECRET, ACCTS)
    assert s.ttl_for(False) == 43200 and s.ttl_for(True) == 2592000
    t = s.issue("admin", remember=True, now=1000.0)
    assert s.verify(t, now=1000.0 + 2592000) == "admin"
    assert s.verify(t, now=1000.0 + 2592001) is None
    t2 = s.issue("admin", now=1000.0)
    assert s.verify(t2, now=1000.0 + 43200) == "admin"
    assert s.verify(t2, now=1000.0 + 43201) is None


async def test_login_cookie_max_age_remember_vs_not():
    # risk: high
    cfg = _acct_cfg()
    async with TestClient(TestServer(_acct_app(cfg))) as c:
        r1 = await _login_as(c, "orange", cfg.orange_pwd, remember=True)
        assert "Max-Age=2592000" in r1.headers["Set-Cookie"]
        r2 = await _login_as(c, "orange", cfg.orange_pwd)
        assert "Max-Age=43200" in r2.headers["Set-Cookie"]
        r3 = await c.get("/login")
        assert 'name="remember"' in await r3.text()


OPS_MARKERS = ('id="anomalies"', 'id="tbl-receiver"', 'id="tbl-devices"', 'id="tbl-calls"', "异常总览", "设备总览", "采集器状态")
NOTICE = "The project dashboard is coming soon."


@pytest.fixture
async def dev_url(db):
    """One throwaway dingtek device (random id), removed afterwards; returns its detail-page path."""
    from lutetia.models import Device
    from lutetia.web.dashboard import device_url
    dev = "t-" + _secrets.token_hex(6)
    await db.upsert_devices([Device(source="dingtek", device_id=dev, name="n-" + dev, device_type="t", expected_online=True, extra={})])
    yield device_url("dingtek", dev)
    async with db.pool.acquire() as conn:
        await conn.execute("DELETE FROM device WHERE device_id = $1", dev)


async def test_admin_ops_pages_show_header_with_escaped_account(db, dev_url):
    # risk: high
    cfg = _acct_cfg(dashboard_user="ad<b>min")
    dev = dev_url
    async with TestClient(TestServer(_acct_app(cfg, db))) as c:
        hdr = _cookie(await _login_as(c, "ad<b>min", cfg.dashboard_pwd))
        for path in ("/dashboard/", dev, "/dashboard/map"):
            r = await c.get(path, headers=hdr)
            body = await r.text()
            assert r.status == 200, path
            assert 'id="whoami"' in body and "ad&lt;b&gt;min" in body and "ad<b>min" not in body, path
            assert 'href="/logout"' in body and NOTICE not in body, path
        body = await (await c.get("/dashboard/", headers=hdr)).text()
        assert 'id="anomalies"' in body and 'id="tbl-receiver"' in body


@pytest.mark.parametrize("user,pwd_attr", [("orange", "orange_pwd"), ("huawei", "huawei_pwd")])
async def test_non_admin_ops_pages_show_only_notice(db, dev_url, user, pwd_attr):
    # risk: high
    cfg = _acct_cfg()
    dev = dev_url
    async with TestClient(TestServer(_acct_app(cfg, db))) as c:
        hdr = _cookie(await _login_as(c, user, getattr(cfg, pwd_attr)))
        for path in ("/dashboard/", dev, "/dashboard/map", "/dashboard/map?tracks=1", "/dashboard/device/dingtek/nope"):
            r = await c.get(path, headers=hdr, allow_redirects=False)
            body = await r.text()
            assert r.status == 200, path
            assert NOTICE in body and 'href="/logout"' in body, path
            assert "<strong>%s</strong>" % user in body and 'id="whoami"' in body, path
            for marker in OPS_MARKERS + ('id="map"', 'id="device"', "map.js", "device.js", "app.js"):
                assert marker not in body, (path, marker)


@pytest.mark.parametrize("path", ["/dashboard/data/overview", "/dashboard/data/telemetry?device_id=x",
                                  "/dashboard/data/positions?device_id=x", "/dashboard/data/map"])
async def test_non_admin_ops_json_is_403_admin_unchanged(db, path):
    # risk: high
    cfg = _acct_cfg()
    async with TestClient(TestServer(_acct_app(cfg, db))) as c:
        for user, pwd in (("orange", cfg.orange_pwd), ("huawei", cfg.huawei_pwd)):
            r = await c.get(path, headers=_cookie(await _login_as(c, user, pwd)))
            assert r.status == 403 and r.content_type == "application/json", (user, path)
            assert "error" in await r.json()
        c.session.cookie_jar.clear()
        assert (await c.get(path)).status == 401  # no session
        c.session.cookie_jar.clear()
        r = await c.get(path, headers=_cookie(await _login_as(c, "admin", cfg.dashboard_pwd)))
        assert r.status not in (401, 403), path


async def test_admin_overview_json_still_served(db):
    # risk: high
    cfg = _acct_cfg()
    async with TestClient(TestServer(_acct_app(cfg, db))) as c:
        r = await c.get("/dashboard/data/overview", headers=_cookie(await _login_as(c, "admin", cfg.dashboard_pwd)))
        assert r.status == 200 and "devices" in await r.json()


async def test_every_session_route_under_dashboard_requires_admin():
    # risk: high  (新增运维路由漏套 require_admin 时在这里被抓：非 admin 的响应里不得出现 handler 内容)
    cfg = _acct_cfg()
    app = _acct_app(cfg)
    paths = [r.resource.canonical for r in app.router.routes() if r.method == "GET" and r.resource.canonical.startswith("/dashboard/")]
    assert len(paths) >= 6
    async with TestClient(TestServer(app)) as c:
        hdr = _cookie(await _login_as(c, "orange", cfg.orange_pwd))
        for p in paths:
            url = p.replace("{source}", "dingtek").replace("{device_id}", "x")
            r = await c.get(url, headers=hdr, allow_redirects=False)
            if url.startswith("/dashboard/data/"):
                assert r.status == 403, url
            else:
                assert r.status == 200 and NOTICE in await r.text(), url


async def test_login_redirects_every_account_to_dashboard_by_default():
    # risk: high
    cfg = _acct_cfg()
    async with TestClient(TestServer(_acct_app(cfg))) as c:
        for user, pwd in (("admin", cfg.dashboard_pwd), ("orange", cfg.orange_pwd), ("huawei", cfg.huawei_pwd)):
            r = await _login_as(c, user, pwd)
            assert r.status == 302 and r.headers["Location"] == "/dashboard/", user


async def test_login_form_input_attributes_for_ios_home_screen():
    # risk: high  (SC-11：用户名不被自动首字母大写)
    async with TestClient(TestServer(_acct_app(_acct_cfg()))) as c:
        body = await (await c.get("/login")).text()
    import re as _re
    user_tag = _re.search(r'<input name="username"[^>]*>', body).group(0)
    pwd_tag = _re.search(r'<input name="password"[^>]*>', body).group(0)
    for attr in ('autocapitalize="none"', 'autocorrect="off"', 'spellcheck="false"', 'autocomplete="username"'):
        assert attr in user_tag, attr
    assert 'autocomplete="current-password"' in pwd_tag


async def test_api_v1_unchanged_by_page_gate(db):
    # risk: high  (8.1 不动 /api/v1：仍只认 Bearer key，不看会话)
    cfg = _acct_cfg()
    async with TestClient(TestServer(_acct_app(cfg, db))) as c:
        hdr = _cookie(await _login_as(c, "orange", cfg.orange_pwd))
        assert (await c.get("/api/v1/devices", headers=hdr)).status == 401
        assert (await c.get("/api/v1/devices", headers={"Authorization": "Bearer " + cfg.api_key})).status == 200


def test_duplicate_account_names_do_not_break_collector_config(monkeypatch):
    # risk: high  (L1：collector 配置加载不检查账号名；只有 web 启动才报错)
    monkeypatch.setenv("ORANGE_USER", "admin")
    monkeypatch.setenv("DASHBOARD_USER", "admin")
    cfg = Config.from_env()  # must not raise
    assert cfg.orange_user == cfg.dashboard_user == "admin"
    with pytest.raises(SystemExit):
        cfg.accounts()
    with pytest.raises(SystemExit):
        _acct_cfg(huawei_user="orange").accounts()


async def test_startup_log_lists_accounts_and_no_password_anywhere(caplog):
    # risk: high
    caplog.set_level(logging.DEBUG)
    cfg = _acct_cfg(huawei_pwd="", dashboard_port=0)
    srv = WebServer(cfg, None, datetime.now(timezone.utc))
    await srv.start()
    try:
        async with TestClient(TestServer(srv.build_app())) as c:
            await _login_as(c, "orange", cfg.orange_pwd, remember=True)
            await _login_as(c, "orange", "wrong-" + _pw())
    finally:
        await srv.stop()
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "web accounts enabled: admin, orange" in text and "huawei" not in text.split("web accounts enabled:")[1].split("\n")[0]
    for secret in (cfg.dashboard_pwd, cfg.orange_pwd, cfg.session_secret):
        assert secret not in text


async def test_missing_session_secret_warns_about_restart(caplog):
    # risk: medium
    caplog.set_level(logging.WARNING)
    srv = WebServer(_acct_cfg(session_secret="", dashboard_port=0), None, datetime.now(timezone.utc))
    await srv.start()
    await srv.stop()
    assert any("SESSION_SECRET" in r.getMessage() and "restart" in r.getMessage() for r in caplog.records)
