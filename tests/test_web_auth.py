# risk: high
"""Task 2.4 contract 1-5: session signer, login limiter, password check (pure functions, no DB)."""
import pytest

from lutetia.web.auth import LoginLimiter, SessionSigner, check_password

SECRET = b"unit-test-secret-0123456789abcdef"


def test_session_roundtrip():
    s = SessionSigner(SECRET)
    token = s.issue("admin", now=1000.0)
    assert s.verify(token, now=1001.0) == "admin"
    # a different secret must not accept it
    assert SessionSigner(b"another-secret-xxxxxxxxxxxxxxxxx").verify(token, now=1001.0) is None


def test_session_tampered_is_rejected():
    s = SessionSigner(SECRET)
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
    s = SessionSigner(SECRET, ttl_seconds=100)
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
    s = SessionSigner(SECRET)
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
    return WebServer(cfg, None, None, datetime.now(timezone.utc)).build_app()


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
