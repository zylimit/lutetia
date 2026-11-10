# risk: high
"""Phase 12 Task 12.1 (THR-2, SC-15, ADR-6): who may frame which path.
- /embed/<widget> (three names only): SPA_CSP with frame-ancestors = EMBED_FRAME_ANCESTORS (default https://*.digifiber.net), no
  X-Frame-Options, Cache-Control no-store; any other /embed path 404 with frame-ancestors 'none' + DENY.
- The framing list is separate from the API callers' CORS origins: a caller's registered origin never shows up in it.
- A bad EMBED_FRAME_ANCESTORS entry is dropped; none valid -> the widgets keep frame-ancestors 'none' + DENY.
- Every other path (SPA, ops dashboard, login, API, static, 404, 503, a marked request that ends in an error) keeps
  frame-ancestors 'none' and X-Frame-Options DENY.
- /api/v1/embed-config answers the same list without any credential.
Fake build in a temp directory, synthetic text only; no database is touched.
"""
import dataclasses
import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from lutetia.config import Config
from lutetia.web.app import WebServer
from lutetia.web.callers import parse_callers
from lutetia.web.embed import DEFAULT_PATTERN, EMBED_CSP, WIDGETS, embed_csp, parse_frame_ancestors
from lutetia.web.spa import SPA_CSP

INDEX = "<!doctype html><title>spa-test-index</title>"
EMBED = "<!doctype html><title>embed-test-page</title>"
CALLER_ORIGIN = "https://caller-only.digifiber.net"  # registered for CORS in the callers file, never a framing origin
OFR = "https://ofr.digifiber.net"
DENY_PATHS = ("/", "/app", "/app/", "/app/manholes", "/app/embed.html", "/app/assets/missing.js", "/dashboard/", "/dashboard/map",
              "/login", "/logout", "/api/v1/summary", "/api/v1/embed-config", "/api/v1/openapi.json", "/static/app.css",
              "/no-such-page", "/embed", "/embed/", "/embed/unknown", "/embed/Fall-Timeline", "/embed/fall-timeline/x",
              "/embed/fall-timeline%2F..%2F..%2Findex.html", "/embed/index.html", "/embed/embed.html")
BAD = ["https://a.digifiber.net;script-src", "'none'", "*", "https://evil-digifiber.net", "https://digifiber.net.evil.com",
       "http://a.digifiber.net", "https://a.digifiber.net:8443", "https://A.digifiber.net", "https://a.digifiber.net/",
       "https://*", "https://*.evil.example", "https://*.*.digifiber.net"]


class NoDB:
    def __getattr__(self, name):
        raise AssertionError("db touched: " + name)


def _entry(origins):
    return {"name": "ariane", "key_sha256": hashlib.sha256(b"k-" + secrets.token_hex(6).encode()).hexdigest(),
            "scopes": ["iot:read"], "origins": origins, "rate_per_min": 60}


def _app(tmp_path, ancestors=None, with_embed=True):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(INDEX, encoding="utf-8")
    if with_embed:
        (dist / "embed.html").write_text(EMBED, encoding="utf-8")
    callers = tmp_path / "callers.json"
    callers.write_text(json.dumps([_entry([CALLER_ORIGIN])]), encoding="utf-8")
    extra = {} if ancestors is None else {"embed_frame_ancestors": ancestors}
    cfg = dataclasses.replace(
        Config.from_env(), dashboard_pwd="t-" + secrets.token_hex(8), api_key="k-" + secrets.token_hex(4),
        dashboard_host="127.0.0.1", login_lockout=False, session_secret="s-" + secrets.token_hex(8), web_ui_dist=dist,
        callers_file=str(callers), **extra)
    return WebServer(cfg, NoDB(), datetime.now(timezone.utc)).build_app()


def _client(tmp_path, **kw):
    return TestClient(TestServer(_app(tmp_path, **kw)))


def _frame_ancestors(r):
    parts = [p.strip() for p in r.headers["Content-Security-Policy"].split(";")]
    found = [p for p in parts if p.startswith("frame-ancestors")]
    assert len(found) == 1, r.headers["Content-Security-Policy"]
    return found[0]


def _assert_deny(r, label):
    assert _frame_ancestors(r) == "frame-ancestors 'none'", label
    assert r.headers.get("X-Frame-Options") == "DENY", label


def test_the_default_is_the_digifiber_pattern(monkeypatch):
    monkeypatch.delenv("EMBED_FRAME_ANCESTORS", raising=False)
    assert Config.from_env().embed_frame_ancestors == DEFAULT_PATTERN == "https://*.digifiber.net"
    monkeypatch.setenv("EMBED_FRAME_ANCESTORS", OFR)
    assert Config.from_env().embed_frame_ancestors == OFR


@pytest.mark.parametrize("name", sorted(WIDGETS))
async def test_widget_pages_may_be_framed_by_digifiber_only(tmp_path, name):
    async with _client(tmp_path) as c:
        r = await c.get("/embed/" + name)
        assert r.status == 200 and await r.text() == EMBED
        assert _frame_ancestors(r) == "frame-ancestors https://*.digifiber.net"
        assert "X-Frame-Options" not in r.headers
        assert r.headers["Cache-Control"] == "no-store"
        csp = r.headers["Content-Security-Policy"]
        assert csp == embed_csp([DEFAULT_PATTERN])
        assert csp.replace(_frame_ancestors(r), "frame-ancestors 'none'") == SPA_CSP  # every other directive unchanged
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert r.headers["X-Content-Type-Options"] == "nosniff"


async def test_caller_origins_are_not_framing_origins(tmp_path):
    async with _client(tmp_path) as c:
        r = await c.get("/embed/fall-timeline")
        assert CALLER_ORIGIN not in r.headers["Content-Security-Policy"]
        body = await (await c.get("/api/v1/embed-config")).json()
        assert body["data"]["origins"] == [DEFAULT_PATTERN]


async def test_narrowed_to_one_host(tmp_path):
    async with _client(tmp_path, ancestors=OFR) as c:
        r = await c.get("/embed/manhole-map")
        assert _frame_ancestors(r) == "frame-ancestors " + OFR and "X-Frame-Options" not in r.headers
        assert (await (await c.get("/api/v1/embed-config")).json())["data"]["origins"] == [OFR]


async def test_bad_entries_are_dropped(tmp_path, caplog):
    raw = " ".join(BAD[:6]) + ", " + OFR + "," + ",".join(BAD[6:]) + " " + OFR
    with caplog.at_level(logging.WARNING, logger="lutetia.web.embed"):
        app = _app(tmp_path, ancestors=raw)
    assert sum("left out" in m for m in caplog.messages) == len(BAD)
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/embed/fall-timeline")
        assert _frame_ancestors(r) == "frame-ancestors " + OFR  # once, in place; nothing of the bad entries
        csp = r.headers["Content-Security-Policy"]
        assert "evil" not in csp and "'none'" not in csp and "script-src 'self';" in csp
        assert (await (await c.get("/api/v1/embed-config")).json())["data"]["origins"] == [OFR]


@pytest.mark.parametrize("raw", ["", "  ,  ", "'none'", "https://evil.example; frame-ancestors *", " ".join(BAD)])
async def test_no_valid_entry_falls_back_to_none(tmp_path, caplog, raw):
    with caplog.at_level(logging.ERROR, logger="lutetia.web.embed"):
        app = _app(tmp_path, ancestors=raw)
    assert any("no valid entry" in m for m in caplog.messages)
    async with TestClient(TestServer(app)) as c:
        r = await c.get("/embed/fall-timeline")
        assert r.status == 200
        _assert_deny(r, "no valid entry")
        assert (await (await c.get("/api/v1/embed-config")).json())["data"]["origins"] == []


def test_only_ascii_space_tab_and_comma_separate_entries(caplog):
    # THR-4: a newline or a no-break space is not a separator; it stays in its entry and the entry is left out with a warning
    assert parse_frame_ancestors("https://a.digifiber.net\t" + OFR + ",https://b.digifiber.net") == [
        "https://a.digifiber.net", OFR, "https://b.digifiber.net"]
    for tail in ("\n", "\r", "\r\n", " \n"):  # a trailing line end (env file, shell) is trimmed, not part of the last entry
        assert parse_frame_ancestors(OFR + tail) == [OFR]
    for odd in ("\n", "\r\n", " ", " "):
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="lutetia.web.embed"):
            assert parse_frame_ancestors(OFR + odd + "https://a.digifiber.net") == []
        assert sum("left out" in m for m in caplog.messages) == 1


def test_wildcards_and_exact_origins_accepted():
    assert parse_frame_ancestors("https://*.digifiber.net https://*.ofr.digifiber.net," + OFR) == [
        DEFAULT_PATTERN, "https://*.ofr.digifiber.net", OFR]


async def test_every_other_path_refuses_framing(tmp_path):
    async with _client(tmp_path) as c:
        for path in DENY_PATHS:
            r = await c.get(path, allow_redirects=False)
            _assert_deny(r, path)
        for path in ("/embed/unknown", "/embed/", "/embed/fall-timeline/x", "/embed/index.html"):
            assert (await c.get(path)).status == 404, path
        r = await c.head("/embed/fall-timeline")  # HEAD is the same widget page
        assert r.status == 200 and "X-Frame-Options" not in r.headers


async def test_a_marked_request_that_ends_in_an_error_is_not_framable(tmp_path):
    """The handler marks the request before it answers; if the answer is not a 200 (raised or returned), DENY stays."""
    app = _app(tmp_path)

    def marked(outcome):
        async def handler(request):
            request[EMBED_CSP] = embed_csp([DEFAULT_PATTERN])
            if outcome == "raise404":
                raise web.HTTPNotFound()
            if outcome == "raise500":
                raise RuntimeError("synthetic failure")
            return web.Response(status=503 if outcome == "503" else 302, text="x")
        return handler

    for outcome in ("raise404", "raise500", "503", "302"):
        app.router.add_get("/marked-" + outcome, marked(outcome))
    async with TestClient(TestServer(app)) as c:
        for outcome in ("raise404", "raise500", "503", "302"):
            r = await c.get("/marked-" + outcome, allow_redirects=False)
            assert r.status != 200, outcome
            _assert_deny(r, outcome)


async def test_ops_dashboard_csp_also_has_frame_ancestors_none(tmp_path):
    async with _client(tmp_path) as c:
        r = await c.get("/login")
        assert "style-src 'self' 'unsafe-inline'" in r.headers["Content-Security-Policy"]  # the old CSP of the ops pages
        _assert_deny(r, "/login")


async def test_widget_without_build_is_503_and_not_framable(tmp_path):
    async with _client(tmp_path, with_embed=False) as c:
        r = await c.get("/embed/fall-timeline")
        assert r.status == 503
        _assert_deny(r, "503")


@pytest.mark.parametrize("bad", ["https://a.digifiber.net; script-src *", "https://a.digifiber.net 'none'", "'none'",
                                 "https://*.digifiber.net", "https://a.digifiber.net\r\nX-Frame-Options: ALLOW"])
def test_registry_file_still_refuses_odd_origins(bad):
    with pytest.raises(SystemExit) as e:
        parse_callers(json.dumps([_entry([bad])]))
    assert "origins" in str(e.value)


async def test_embed_config_needs_no_credential_and_matches_the_header(tmp_path):
    async with _client(tmp_path, ancestors="https://*.digifiber.net " + OFR) as c:
        r = await c.get("/api/v1/embed-config")
        assert r.status == 200
        body = await r.json()
        assert set(body) == {"data", "as_of"} and body["as_of"].endswith("Z")
        assert body["data"] == {"origins": [DEFAULT_PATTERN, OFR]}
        page = await c.get("/embed/security-summary")
        assert _frame_ancestors(page) == "frame-ancestors " + " ".join(body["data"]["origins"])
        r = await c.get("/api/v1/embed-config", headers={"Authorization": "Bearer nope"})  # a bad key changes nothing here
        assert r.status == 200
