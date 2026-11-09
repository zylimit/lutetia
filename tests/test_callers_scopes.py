# risk: high
"""Task 8.2 补洞：限流按调用方 / 按账号隔离（key 与会话的桶互不串）、api 日志行在 429 与各账号下的格式与不泄凭据。
已由 test_callers.py 覆盖、此处不重复：会话范围（admin 200 / 其他 403 on status，三账号读 devices/positions/telemetry 都 200）、
key 间 429 隔离、orange 429 时 huawei 200、基本日志行格式（key / session:orange / -）。"""
import logging

from aiohttp import DummyCookieJar
from aiohttp.test_utils import TestClient, TestServer

from test_callers import Clock, bearer, entry, make_app, mk_key, sha
from lutetia.web import callers as callers_mod

DEV = "/api/v1/devices"


async def _cookies(c, cfg):
    out = {}
    for user, pwd in (("admin", cfg.dashboard_pwd), ("orange", cfg.orange_pwd), ("huawei", cfg.huawei_pwd)):
        r = await c.post("/login", data={"username": user, "password": pwd, "next": ""}, allow_redirects=False)
        out[user] = {"Cookie": "lutetia_session=" + r.cookies["lutetia_session"].value}
    return out


async def _statuses(c, headers, n, path=DEV):
    return [(await c.get(path, headers=headers)).status for _ in range(n)]


async def test_buckets_isolated_between_keys_and_sessions_both_directions(tmp_path):
    key = mk_key()
    # a registered caller literally named like an account must not share that account's session bucket
    zkey = mk_key()
    app, cfg = make_app(tmp_path, [entry("orange", key, rate=2), entry("zed", zkey, rate=2)],
                        session_rate_per_min=2, api_key="k-" + mk_key())
    app["ctx"].callers.clock = Clock()
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        ck = await _cookies(c, cfg)
        assert await _statuses(c, bearer(key), 3) == [200, 200, 429]            # key "orange" exhausted
        assert await _statuses(c, bearer(zkey), 2) == [200, 200]                # other key untouched
        assert await _statuses(c, ck["orange"], 2) == [200, 200]                # session orange untouched
        assert await _statuses(c, ck["orange"], 1) == [429]                     # now the session is exhausted
        assert await _statuses(c, ck["admin"], 2) == [200, 200]                 # admin unaffected by orange
        assert await _statuses(c, ck["admin"], 1) == [429]
        assert await _statuses(c, ck["huawei"], 2) == [200, 200]                # huawei unaffected by admin
        assert await _statuses(c, bearer(mk_key()), 1) == [401]                 # unknown key never spends anyone's bucket


async def test_log_lines_for_429_admin_session_and_no_credential_anywhere(tmp_path, caplog):
    key, wrong = mk_key(), mk_key()
    app, cfg = make_app(tmp_path, [entry("ariane", key, rate=1)], api_key="k-" + mk_key())
    app["ctx"].callers.clock = Clock()
    caplog.set_level(logging.DEBUG)
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        ck = await _cookies(c, cfg)
        await c.get(DEV + "?secret=q1", headers=bearer(key))
        await c.get(DEV + "?secret=q2", headers=bearer(key))              # 429
        await c.get("/api/v1/status", headers=ck["admin"])
        await c.get("/api/v1/status", headers=ck["huawei"])               # 403
        await c.get(DEV + "?secret=q3", headers=bearer(wrong))            # 401
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("api ")]
    assert lines == ["api caller=ariane resource=/api/v1/devices status=200",
                     "api caller=ariane resource=/api/v1/devices status=429",
                     "api caller=session:admin resource=/api/v1/status status=200",
                     "api caller=session:huawei resource=/api/v1/status status=403",
                     "api caller=- resource=/api/v1/devices status=401"]
    # every logger except aiohttp's own access log (outside this task): no key, digest, wrong key, session token, header text or query
    text = "\n".join(r.getMessage() + " " + str(r.args) for r in caplog.records if not r.name.startswith("aiohttp"))
    tokens = [ck[u]["Cookie"].split("=", 1)[1] for u in ck]
    for secret in [key, sha(key), wrong, sha(wrong), cfg.dashboard_pwd, cfg.orange_pwd, "Authorization", "Bearer", "secret=", "q1", "q3"] + tokens:
        assert secret not in text, "leaked into logs: %s..." % secret[:4]
    assert callers_mod.log.name in {r.name for r in caplog.records}
