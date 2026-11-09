# risk: high
"""Task 8.2: caller registry, scopes, rate limit, CORS, log line. No database: a stub Database serves fixed rows.
Every key and digest is generated at run time."""
import dataclasses
import hashlib
import json
import logging
import re
import secrets
from datetime import datetime, timezone

import pytest
from aiohttp import DummyCookieJar
from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config
from lutetia.web import WebServer
from lutetia.web import callers as callers_mod

T0 = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)
ORIGIN_A, ORIGIN_B = "https://ofr.digifiber.net", "https://other.example.org"
# Near misses of ORIGIN_A. Matching is exact and case-sensitive on the whole string (browsers send a lowercase Origin).
NEAR_MISSES = ["https://evil-ofr.digifiber.net", "https://ofr.digifiber.net.evil.com", "http://ofr.digifiber.net",
               "https://OFR.digifiber.net", "https://ofr.digifiber.net:8443", "https://digifiber.net", "https://x.ofr.digifiber.net"]


class FakeDB:
    async def list_devices(self):
        return [{"source": "dingtek", "device_id": "dev-1", "name": "n1", "device_type": "DC414",
                 "expected_online": True, "last_ts": T0}]

    async def query_positions(self, device_id, since, until, limit):
        return [{"device_id": device_id, "update_time": T0, "lat": 1.5, "lon": 2.5}]

    async def query_telemetry(self, device_id, key, since, until, limit):
        return [{"device_id": device_id, "key": key or "volt", "ts": T0, "value_si": 3.6}]

    async def collector_status(self):
        return None

    async def call_summary(self, hours):
        return [{"api": "gps51", "n": 3}]


def mk_key():
    return secrets.token_hex(16)


def sha(key):
    return hashlib.sha256(key.encode()).hexdigest()


def entry(name, key, scopes=("iot:read",), origins=(), rate=100):
    return {"name": name, "key_sha256": sha(key), "scopes": list(scopes), "origins": list(origins), "rate_per_min": rate}


def make_app(tmp_path, entries=None, raw=None, **cfg_kw):
    base = dict(api_key=cfg_kw.pop("api_key", ""), dashboard_pwd="p-" + secrets.token_hex(4),
                orange_pwd="o-" + secrets.token_hex(4), huawei_pwd="h-" + secrets.token_hex(4),
                dashboard_host="127.0.0.1", login_lockout=False, session_secret="s-" + secrets.token_hex(8),
                callers_file="")
    if entries is not None or raw is not None:
        f = tmp_path / "callers.json"
        f.write_text(raw if raw is not None else json.dumps(entries), encoding="utf-8")
        base["callers_file"] = str(f)
    base.update(cfg_kw)
    cfg = dataclasses.replace(Config.from_env(), **base)
    return WebServer(cfg, FakeDB(), T0).build_app(), cfg


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def bearer(key):
    return {"Authorization": "Bearer " + key}


async def test_no_key_and_wrong_key_are_401(tmp_path):
    key = mk_key()
    app, _ = make_app(tmp_path, [entry("ariane", key)])
    async with TestClient(TestServer(app)) as c:
        for headers in ({}, bearer(mk_key()), {"Authorization": "Basic " + key}, {"Authorization": "Bearer"}):
            r = await c.get("/api/v1/devices", headers=headers, allow_redirects=False)
            assert r.status == 401, headers
            assert r.headers["WWW-Authenticate"] == "Bearer"
            assert await r.json() == {"error": "unauthorized"}
        assert (await c.get("/api/v1/devices", headers=bearer(key))).status == 200


async def test_out_of_scope_is_403_without_data(tmp_path):
    key = mk_key()
    app, _ = make_app(tmp_path, [entry("ariane", key, scopes=["iot:read"]), entry("mon", mk_key(), scopes=["status:read"])])
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/api/v1/status", headers=bearer(key))
        assert r.status == 403
        assert await r.json() == {"error": "forbidden"}
        assert (await c.get("/api/v1/devices", headers=bearer(key))).status == 200


async def test_status_scope_alone_cannot_read_iot(tmp_path):
    key = mk_key()
    app, _ = make_app(tmp_path, [entry("mon", key, scopes=["status:read"])])
    async with TestClient(TestServer(app)) as c:
        assert (await c.get("/api/v1/status", headers=bearer(key))).status == 200
        for path in ("/api/v1/devices", "/api/v1/positions?device_id=x", "/api/v1/telemetry?device_id=x"):
            assert (await c.get(path, headers=bearer(key))).status == 403, path


async def test_rate_limit_429_retry_after_and_recovery(tmp_path):
    k1, k2 = mk_key(), mk_key()
    app, _ = make_app(tmp_path, [entry("a", k1, rate=3), entry("b", k2, rate=3)])
    clock = Clock()
    app["ctx"].callers.clock = clock
    async with TestClient(TestServer(app)) as c:
        for _ in range(3):
            assert (await c.get("/api/v1/devices", headers=bearer(k1))).status == 200
        r = await c.get("/api/v1/devices", headers=bearer(k1))
        assert r.status == 429
        assert r.headers["Retry-After"] == "20"  # 1 token at 3 / min = 20 s
        assert await r.json() == {"error": "rate limit exceeded"}
        assert (await c.get("/api/v1/devices", headers=bearer(k2))).status == 200  # other callers are separate
        clock.t += 19
        assert (await c.get("/api/v1/devices", headers=bearer(k1))).status == 429
        assert int((await c.get("/api/v1/devices", headers=bearer(k1))).headers["Retry-After"]) >= 1
        clock.t += 1
        assert (await c.get("/api/v1/devices", headers=bearer(k1))).status == 200
        clock.t += 600  # refill is capped at capacity
        assert [(await c.get("/api/v1/devices", headers=bearer(k1))).status for _ in range(4)] == [200, 200, 200, 429]


async def test_cors_only_for_the_callers_own_registered_origins(tmp_path):
    ka, kb = mk_key(), mk_key()
    app, _ = make_app(tmp_path, [entry("a", ka, origins=[ORIGIN_A]), entry("b", kb, origins=[])])
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/api/v1/devices", headers=dict(bearer(ka), Origin=ORIGIN_A))
        assert r.headers["Access-Control-Allow-Origin"] == ORIGIN_A
        assert r.headers["Vary"] == "Origin" and r.headers["Access-Control-Allow-Credentials"] == "true"
        for headers in (dict(bearer(ka), Origin=ORIGIN_B), dict(bearer(kb), Origin=ORIGIN_A), bearer(ka),
                        dict(bearer(mk_key()), Origin=ORIGIN_A), dict(Origin=ORIGIN_A)):
            r = await c.get("/api/v1/devices", headers=headers)
            assert not [h for h in r.headers if h.lower().startswith("access-control")], headers
        r = await c.get("/api/v1/status", headers=dict(bearer(ka), Origin=ORIGIN_A))  # 403 still readable by the browser
        assert r.status == 403 and r.headers["Access-Control-Allow-Origin"] == ORIGIN_A
        for origin in (ORIGIN_A, ORIGIN_B, "null"):
            r = await c.get("/api/v1/devices", headers=dict(bearer(ka), Origin=origin))
            assert r.headers.get("Access-Control-Allow-Origin") != "*"


async def test_cors_near_miss_origins_get_no_cors_headers_actual_and_preflight(tmp_path):
    ka = mk_key()
    app, _ = make_app(tmp_path, [entry("a", ka, origins=[ORIGIN_A])])
    async with TestClient(TestServer(app)) as c:
        for origin in NEAR_MISSES:
            r = await c.get("/api/v1/devices", headers=dict(bearer(ka), Origin=origin))
            assert r.status == 200
            assert not [h for h in r.headers if h.lower().startswith("access-control")], origin
            r = await c.options("/api/v1/devices", headers={"Origin": origin, "Access-Control-Request-Method": "GET",
                                                            "Access-Control-Request-Headers": "authorization"})
            assert r.status == 204
            assert not [h for h in r.headers if h.lower().startswith("access-control")], origin
        # control: the exact origin still works on both paths
        r = await c.get("/api/v1/devices", headers=dict(bearer(ka), Origin=ORIGIN_A))
        assert r.headers["Access-Control-Allow-Origin"] == ORIGIN_A
        r = await c.options("/api/v1/devices", headers={"Origin": ORIGIN_A, "Access-Control-Request-Method": "GET"})
        assert r.headers["Access-Control-Allow-Origin"] == ORIGIN_A


async def test_cors_responses_expose_retry_after_but_401_has_no_cors(tmp_path):
    ka = mk_key()
    app, _ = make_app(tmp_path, [entry("a", ka, origins=[ORIGIN_A], rate=1)])
    app["ctx"].callers.clock = Clock()
    async with TestClient(TestServer(app)) as c:
        h = dict(bearer(ka), Origin=ORIGIN_A)
        r = await c.get("/api/v1/devices", headers=h)
        assert r.status == 200 and r.headers["Access-Control-Expose-Headers"] == "Retry-After"
        r = await c.get("/api/v1/devices", headers=h)
        assert r.status == 429 and r.headers["Access-Control-Expose-Headers"] == "Retry-After" and "Retry-After" in r.headers
        r = await c.options("/api/v1/devices", headers={"Origin": ORIGIN_A, "Access-Control-Request-Method": "GET"})
        assert r.headers["Access-Control-Expose-Headers"] == "Retry-After"
        r = await c.get("/api/v1/devices", headers=dict(bearer(mk_key()), Origin=ORIGIN_A))
        assert r.status == 401 and not [x for x in r.headers if x.lower().startswith("access-control")]


async def test_preflight(tmp_path):
    app, _ = make_app(tmp_path, [entry("a", mk_key(), origins=[ORIGIN_A])])
    async with TestClient(TestServer(app)) as c:
        r = await c.options("/api/v1/devices", headers={"Origin": ORIGIN_A, "Access-Control-Request-Method": "GET",
                                                        "Access-Control-Request-Headers": "authorization"})
        assert r.status == 204
        assert r.headers["Access-Control-Allow-Origin"] == ORIGIN_A
        assert r.headers["Access-Control-Allow-Methods"] == "GET"
        assert r.headers["Access-Control-Allow-Headers"] == "Authorization"
        assert r.headers["Access-Control-Allow-Credentials"] == "true" and r.headers["Vary"] == "Origin"
        for headers in ({"Origin": ORIGIN_B, "Access-Control-Request-Method": "GET"},
                        {"Origin": ORIGIN_A, "Access-Control-Request-Method": "POST"},
                        {"Access-Control-Request-Method": "GET"}):
            r = await c.options("/api/v1/devices", headers=headers)
            assert not [h for h in r.headers if h.lower().startswith("access-control")], headers
    for route in app.router.routes():
        path = getattr(getattr(route, "resource", None), "canonical", "") or ""
        if path.startswith("/api/"):
            assert route.method in ("GET", "HEAD")


async def test_log_line_names_caller_but_never_key_digest_or_query(tmp_path, caplog):
    key = mk_key()
    app, cfg = make_app(tmp_path, [entry("ariane", key)])
    caplog.set_level(logging.DEBUG)
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        await c.get("/api/v1/positions?device_id=dev-1&lat=48.85661&lon=2.35222", headers=bearer(key))
        await c.get("/api/v1/status", headers=bearer(key))
        await c.get("/api/v1/devices", headers=bearer(mk_key()))
        await c.get("/api/v1/devices")
        r = await c.post("/login", data={"username": "orange", "password": cfg.orange_pwd, "next": ""}, allow_redirects=False)
        await c.get("/api/v1/devices", headers={"Cookie": "lutetia_session=" + r.cookies["lutetia_session"].value})
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("api ")]
    assert lines == ["api caller=ariane resource=/api/v1/positions status=200",
                     "api caller=ariane resource=/api/v1/status status=403",
                     "api caller=- resource=/api/v1/devices status=401",
                     "api caller=- resource=/api/v1/devices status=401",
                     "api caller=session:orange resource=/api/v1/devices status=200"]
    # aiohttp's own access logger (not ours) writes the raw query string; this task's logger must not.
    text = "\n".join(r.getMessage() for r in caplog.records if r.name == callers_mod.log.name)
    assert text and key not in text and sha(key) not in text and "48.85" not in text and "2.352" not in text


BAD_FILES = [
    ("not json", "{oops", "not valid JSON"),
    ("not array", "{}", "JSON array"),
    ("item not object", "[1]", "item 1: must be a JSON object"),
    ("unknown field", lambda k: [dict(entry("a", k), extra=1)], "item 1: unknown field 'extra'"),
    ("missing field", lambda k: [{kk: v for kk, v in entry("a", k).items() if kk != "origins"}], "item 1: missing field 'origins'"),
    ("bad name", lambda k: [entry("a b", k)], "item 1: field 'name'"),
    ("name legacy", lambda k: [entry("legacy", k)], "item 1: field 'name' may not be 'legacy'"),
    ("duplicate name", lambda k: [entry("a", k), entry("a", mk_key())], "items 1 and 2: duplicate 'name'"),
    ("duplicate key", lambda k: [entry("a", k), entry("b", k)], "items 1 and 2: duplicate 'key_sha256'"),
    ("uppercase digest", lambda k: [dict(entry("a", k), key_sha256=sha(k).upper())], "item 1: field 'key_sha256'"),
    ("short digest", lambda k: [dict(entry("a", k), key_sha256=sha(k)[:63])], "item 1: field 'key_sha256'"),
    ("unknown scope", lambda k: [entry("a", k, scopes=["iot:read", "iot:write"])], "item 1: field 'scopes' has an unknown scope"),
    ("empty scopes", lambda k: [entry("a", k, scopes=[])], "item 1: field 'scopes' must be a non-empty"),
    ("origin http", lambda k: [entry("a", k, origins=["http://a.digifiber.net"])], "item 1: field 'origins' entry 1"),
    ("origin wildcard", lambda k: [entry("a", k, origins=["https://*.digifiber.net"])], "item 1: field 'origins' entry 1"),
    ("origin path", lambda k: [entry("a", k, origins=["https://a.digifiber.net/x"])], "item 1: field 'origins' entry 1"),
    ("origin trailing slash", lambda k: [entry("a", k, origins=["https://a.digifiber.net/"])], "item 1: field 'origins' entry 1"),
    ("origin port", lambda k: [entry("a", k, origins=["https://a.digifiber.net:8443"])], "item 1: field 'origins' entry 1"),
    ("origin bare apex", lambda k: [entry("a", k, origins=["https://digifiber.net"])], "item 1: field 'origins' entry 1"),
    ("origin dot apex", lambda k: [entry("a", k, origins=["https://.digifiber.net"])], "item 1: field 'origins' entry 1"),
    ("origin empty label", lambda k: [entry("a", k, origins=["https://a..digifiber.net"])], "item 1: field 'origins' entry 1"),
    ("origin other domain", lambda k: [entry("a", k, origins=["https://a.example.net"])], "item 1: field 'origins' entry 1"),
    ("origin lookalike suffix", lambda k: [entry("a", k, origins=["https://a.digifiber.net.evil.com"])], "item 1: field 'origins' entry 1"),
    ("origin glued suffix", lambda k: [entry("a", k, origins=["https://evildigifiber.net"])], "item 1: field 'origins' entry 1"),
    ("origin userinfo", lambda k: [entry("a", k, origins=["https://x@a.digifiber.net"])], "item 1: field 'origins' entry 1"),
    ("origin uppercase", lambda k: [entry("a", k, origins=["https://A.digifiber.net"])], "item 1: field 'origins' entry 1"),
    ("origin not string", lambda k: [entry("a", k, origins=[5])], "item 1: field 'origins' entry 1"),
    ("origin second entry bad", lambda k: [entry("a", k, origins=["https://a.digifiber.net", "https://b.example.org"])],
     "item 1: field 'origins' entry 2"),
    ("empty key digest", lambda k: [dict(entry("a", k), key_sha256=hashlib.sha256(b"").hexdigest())], "item 1: field 'key_sha256' is the digest of an empty key"),
    ("rate zero", lambda k: [entry("a", k, rate=0)], "item 1: field 'rate_per_min'"),
    ("rate bool", lambda k: [dict(entry("a", k), rate_per_min=True)], "item 1: field 'rate_per_min'"),
    ("rate string", lambda k: [dict(entry("a", k), rate_per_min="5")], "item 1: field 'rate_per_min'"),
    ("second item bad", lambda k: [entry("a", mk_key()), entry("b", k, rate=-1)], "item 2: field 'rate_per_min'"),
]


@pytest.mark.parametrize("label,build,expect", BAD_FILES, ids=[b[0] for b in BAD_FILES])
def test_bad_registry_file_refuses_to_start_without_leaking_key(tmp_path, label, build, expect):
    key = mk_key()
    raw = build if isinstance(build, str) else json.dumps(build(key))
    with pytest.raises(SystemExit) as ei:
        make_app(tmp_path, raw=raw)
    msg = str(ei.value)
    assert expect in msg, msg
    assert key not in msg and sha(key) not in msg and sha(key).upper() not in msg


def test_registry_file_missing_and_legacy_digest_clash(tmp_path):
    with pytest.raises(SystemExit) as ei:
        make_app(tmp_path, callers_file=str(tmp_path / "nope.json"))
    assert "cannot read CALLERS_FILE" in str(ei.value)
    key = mk_key()
    with pytest.raises(SystemExit) as ei:
        make_app(tmp_path, [entry("a", key)], api_key=key)
    assert "duplicates the legacy API_KEY" in str(ei.value) and key not in str(ei.value)
    with pytest.raises(SystemExit):
        make_app(tmp_path, [], legacy_rate_per_min=0)


async def test_legacy_key_responses_match_pre_change_shape(tmp_path):
    # Expected bodies were fixed from lutetia/web/api.py as of HEAD 636a7a7 (before this task).
    key = mk_key()
    app, _ = make_app(tmp_path, api_key=key)
    h = bearer(key)
    stamp = "2026-11-09T12:00:00Z"
    async with TestClient(TestServer(app)) as c:
        async def body(path):
            r = await c.get(path, headers=h)
            assert r.status == 200, path
            assert r.content_type == "application/json"
            return await r.json()

        assert await body("/api/v1/devices") == {"devices": [
            {"source": "dingtek", "device_id": "dev-1", "name": "n1", "device_type": "DC414", "expected_online": True, "last_ts": stamp}]}
        assert await body("/api/v1/positions?device_id=dev-1") == {"device_id": "dev-1", "count": 1, "positions": [
            {"device_id": "dev-1", "update_time": stamp, "lat": 1.5, "lon": 2.5}]}
        assert await body("/api/v1/telemetry?device_id=dev-1&key=volt") == {"device_id": "dev-1", "count": 1, "telemetry": [
            {"device_id": "dev-1", "key": "volt", "ts": stamp, "value_si": 3.6}]}
        st = await body("/api/v1/status")
        assert st == {"started_at": stamp, "receiver": None, "api_calls_24h": [{"api": "gps51", "n": 3}], "collector": {
            "updated_at": None, "age_sec": None, "stale": True, "version": None, "ws_connected": None, "polling": None,
            "push_last_at": None, "push_count_24h": None, "collector_started_at": None}}
        r = await c.get("/api/v1/positions", headers=h)  # 400 shape unchanged
        assert r.status == 400 and await r.json() == {"error": "device_id required"}
        r = await c.get("/api/v1/devices", headers=bearer("wrong"))
        assert r.status == 401 and r.headers["WWW-Authenticate"] == "Bearer"
        assert (await c.get("/api/v1/devices", headers={"Authorization": "bearer  " + key + " "})).status == 200


async def test_legacy_has_own_rate_limit(tmp_path):
    key = mk_key()
    app, _ = make_app(tmp_path, api_key=key, legacy_rate_per_min=2)
    app["ctx"].callers.clock = Clock()
    async with TestClient(TestServer(app)) as c:
        assert [(await c.get("/api/v1/devices", headers=bearer(key))).status for _ in range(3)] == [200, 200, 429]


async def test_without_callers_file_only_legacy_exists(tmp_path):
    key = mk_key()
    app, _ = make_app(tmp_path, api_key=key)
    assert [x.name for x in app["ctx"].callers.callers] == ["legacy"]
    app, _ = make_app(tmp_path, api_key="")
    async with TestClient(TestServer(app)) as c:
        assert (await c.get("/api/v1/devices", headers=bearer(key))).status == 401
        assert (await c.get("/api/v1/devices", headers=bearer(""))).status == 401


async def test_session_cookie_calls_api_and_limits_per_account(tmp_path):
    app, cfg = make_app(tmp_path, [], session_rate_per_min=2, api_key="k-" + mk_key())  # no cookie jar: send cookies by hand
    clock = Clock()
    app["ctx"].callers.clock = clock
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        cookies = {}
        for user, pwd in (("admin", cfg.dashboard_pwd), ("orange", cfg.orange_pwd), ("huawei", cfg.huawei_pwd)):
            r = await c.post("/login", data={"username": user, "password": pwd, "next": ""}, allow_redirects=False)
            cookies[user] = {"Cookie": "lutetia_session=" + r.cookies["lutetia_session"].value}
        assert [(await c.get("/api/v1/devices", headers=cookies["orange"])).status for _ in range(2)] == [200, 200]
        r = await c.get("/api/v1/devices", headers=cookies["orange"])
        assert r.status == 429 and int(r.headers["Retry-After"]) >= 1
        assert (await c.get("/api/v1/devices", headers=cookies["huawei"])).status == 200  # separate bucket
        assert (await c.get("/api/v1/devices", headers=dict(cookies["huawei"], Authorization="Bearer wrong"))).status == 401
        assert (await c.get("/api/v1/devices", headers={"Cookie": "lutetia_session=garbage"})).status == 401
        assert not [h for h in (await c.get("/api/v1/devices", headers=dict(cookies["huawei"], Origin=ORIGIN_A))).headers
                    if h.lower().startswith("access-control")]


async def test_removed_caller_gets_401_after_rebuild(tmp_path):
    ka, kb = mk_key(), mk_key()
    entries = [entry("ariane", ka), entry("other", kb)]
    app, _ = make_app(tmp_path, entries)
    async with TestClient(TestServer(app)) as c:
        assert (await c.get("/api/v1/devices", headers=bearer(ka))).status == 200
    app, _ = make_app(tmp_path, entries[1:])
    async with TestClient(TestServer(app)) as c:
        assert (await c.get("/api/v1/devices", headers=bearer(ka))).status == 401
        assert (await c.get("/api/v1/devices", headers=bearer(kb))).status == 200


def test_authenticate_compares_against_every_caller_without_early_return(monkeypatch):
    keys = [mk_key() for _ in range(4)]
    reg = callers_mod.CallerRegistry([callers_mod.Caller("c%d" % i, bytes.fromhex(sha(k)), frozenset(["iot:read"]), frozenset(), 5)
                                      for i, k in enumerate(keys)])
    calls = []
    real = callers_mod.hmac.compare_digest
    monkeypatch.setattr(callers_mod.hmac, "compare_digest", lambda a, b: calls.append(1) or real(a, b))
    assert reg.authenticate(keys[0]).name == "c0"
    assert len(calls) == 4
    del calls[:]
    assert reg.authenticate(mk_key()) is None and len(calls) == 4


def test_token_bucket_math():
    clock = Clock()
    reg = callers_mod.CallerRegistry([], clock=clock)
    assert [reg.take("x", 60) for _ in range(60)] == [0] * 60
    assert reg.take("x", 60) == 1
    clock.t += 0.5
    assert reg.take("x", 60) == 1  # half a token is not enough
    clock.t += 0.5
    assert reg.take("x", 60) == 0


def test_origin_allowed_accepts_one_or_more_labels_under_digifiber():
    assert callers_mod.origin_allowed("https://ofr.digifiber.net")
    assert callers_mod.origin_allowed("https://a-1.b.digifiber.net")
    assert not callers_mod.origin_allowed("https://digifiber.net")
    assert callers_mod.ORIGIN_SUFFIX == ".digifiber.net"


async def test_non_bearer_authorization_is_401_even_with_valid_session_or_registered_key(tmp_path):
    key = mk_key()
    app, cfg = make_app(tmp_path, [entry("a", key)], api_key="k-" + mk_key())
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        r = await c.post("/login", data={"username": "admin", "password": cfg.dashboard_pwd, "next": ""}, allow_redirects=False)
        cookie = {"Cookie": "lutetia_session=" + r.cookies["lutetia_session"].value}
        assert (await c.get("/api/v1/devices", headers=cookie)).status == 200
        for auth in ("Basic " + key, "Token " + key, "Bearer", "Bearer ", "Bearer    ", key, ""):
            for extra in ({}, cookie):
                r = await c.get("/api/v1/devices", headers=dict(extra, Authorization=auth))
                assert r.status == 401, (auth, bool(extra))
                assert r.headers["WWW-Authenticate"] == "Bearer"
                assert await r.json() == {"error": "unauthorized"}
        log_before = len(app["ctx"].callers._buckets)
        assert (await c.get("/api/v1/devices", headers={"Authorization": "Basic x"})).status == 401
        assert len(app["ctx"].callers._buckets) == log_before  # never reached the rate limiter


async def test_session_scopes_follow_account_admin_gets_status_others_403(tmp_path):
    app, cfg = make_app(tmp_path, [], api_key="k-" + mk_key())
    paths = ["/api/v1/devices", "/api/v1/positions?device_id=dev-1", "/api/v1/telemetry?device_id=dev-1"]
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        for user, pwd in (("admin", cfg.dashboard_pwd), ("orange", cfg.orange_pwd), ("huawei", cfg.huawei_pwd)):
            r = await c.post("/login", data={"username": user, "password": pwd, "next": ""}, allow_redirects=False)
            hdr = {"Cookie": "lutetia_session=" + r.cookies["lutetia_session"].value}
            for path in paths:
                assert (await c.get(path, headers=hdr)).status == 200, (user, path)
            r = await c.get("/api/v1/status", headers=hdr)
            if user == "admin":
                assert r.status == 200 and "api_calls_24h" in await r.json()
            else:
                assert r.status == 403, user
                assert await r.json() == {"error": "forbidden"}  # no ops data in the body


def test_session_admin_decision_is_auth_is_admin():
    import inspect
    from lutetia.web import auth
    src = inspect.getsource(auth.require_api)
    assert "is_admin(" in src
    assert "dashboard_user" not in inspect.getsource(callers_mod)
