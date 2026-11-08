# risk: high
"""Phase 7 cross-Task wiring (7.1 role/view + 7.2 heartbeat + 7.3 compose/nginx/cli): the pieces named in one file must agree
with the pieces named in another. Static text checks need no database; the ro-web test needs the local DB and is skipped without it."""
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

import lutetia.cli
from lutetia import heartbeat
from lutetia.config import Config
from lutetia.db import Database
from lutetia.web import WebServer
from test_map_page import make_cfg
from test_readonly_role import DB_URL, _restore, _ro_state, ro_url

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
NGINX = (ROOT / "deploy" / "nginx" / "iot.digifiber.net.conf").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")


def _nocomment(text):
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


def _service(name):
    m = re.search(r"^  %s:\n((?:(?:    .*)?\n)+)" % name, COMPOSE, re.M)
    assert m, name
    return _nocomment(m.group(1))


def _nginx_location_ports():
    """{location line: upstream port} from the nginx conf."""
    out = {}
    for m in re.finditer(r"location\s+([^{]+?)\s*\{(.*?)\n    \}", NGINX, re.S):
        port = re.search(r"proxy_pass http://127\.0\.0\.1:(\d+)", m.group(2))
        assert port, m.group(1)
        out[m.group(1).strip()] = int(port.group(1))
    return out


def test_compose_commands_are_accepted_by_the_real_cli_parser():
    # a typo in the compose command (flag name, role value) would only show up as a restart loop on fra
    parser = lutetia.cli.build_parser()
    for svc, role in (("collector", "collector"), ("web", "web")):
        m = re.search(r"^\s+command: (.+)$", _service(svc), re.M)
        assert m, svc
        cmd = m.group(1)
        runs = re.findall(r"lutetia (run[^&|\"\]]*)", cmd.replace('", "', " "))
        assert len(runs) == 1, cmd
        args = parser.parse_args(runs[0].replace('"', "").split())
        assert args.role == role, (svc, args.role)
    assert parser.parse_args(["migrate"]).fn is lutetia.cli.cmd_migrate


def test_nginx_routes_push_and_health_to_collector_port_and_rest_to_web_port():
    ports = _nginx_location_ports()
    col_container = int(re.search(r'"127\.0\.0\.1:\$\{PUSH_PUBLISH_PORT:-(\d+)\}:(\d+)"', _service("collector")).group(1))
    assert ports["^~ /gps51/push"] == col_container and ports["= /health"] == col_container
    assert ports["/"] != col_container        # ADR-1: dashboard and push intake must not share one upstream


def test_nginx_default_push_path_matches_receiver_default(monkeypatch):
    monkeypatch.delenv("PUSH_PATH", raising=False)
    assert Config.from_env().push_path.startswith("/gps51/push")
    assert "location ^~ /gps51/push" in NGINX


def test_env_example_lists_every_variable_compose_requires():
    required = set(re.findall(r"\$\{([A-Z_0-9]+):\?", COMPOSE))
    assert {"DATABASE_RO_PASSWORD", "DASHBOARD_PWD", "API_KEY"} <= required
    listed = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", ENV_EXAMPLE, re.M))
    assert required <= listed, sorted(required - listed)


def test_heartbeat_interval_is_below_half_the_stale_threshold():
    # one lost beat must not turn the dashboard red: 2 x interval <= threshold (30 s beat vs 90 s threshold)
    from lutetia.web import anomalies
    assert 2 * heartbeat.HEARTBEAT_SEC <= anomalies.HEARTBEAT_STALE_SEC


@pytest.fixture
async def ro_db():
    if not DB_URL:
        pytest.skip("DATABASE_URL not set")
    admin = Database(DB_URL)
    try:
        await admin.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip("database unreachable: %s" % e)
    await admin.migrate(lutetia.cli.SQL_DIR)
    async with admin.pool.acquire() as c:
        state = await _ro_state(c)
    old = os.environ.get("DATABASE_RO_PASSWORD")
    pw = secrets.token_hex(16)
    os.environ["DATABASE_RO_PASSWORD"] = pw
    ro = Database(ro_url(pw))
    try:
        await admin.migrate(lutetia.cli.SQL_DIR)
        await ro.connect()
        yield admin, ro
    finally:
        await ro.close()
        if old is None:
            os.environ.pop("DATABASE_RO_PASSWORD", None)
        else:
            os.environ["DATABASE_RO_PASSWORD"] = old
        async with admin.pool.acquire() as c:
            await _restore(c, state)
        await admin.close()


class _Rcv:
    received = stored = rejected = unrecognised = alarms = failed = 0
    last_position_wall = None
    queue = type("Q", (), {"qsize": staticmethod(lambda: 0)})()
    silent_for = message_silent_for = staticmethod(lambda: 0.0)


class _Poller:
    polling = False


async def test_every_parameterless_get_route_works_when_web_connects_as_lutetia_ro(ro_db):
    # the collector writes the heartbeat with the admin account; the web process (read-only role) must render every page from it
    admin, ro = ro_db
    assert await heartbeat.write_once(admin, _Rcv(), _Poller(), None)
    cfg = make_cfg()
    app = WebServer(cfg, ro, datetime.now(timezone.utc)).build_app()
    paths = sorted({r.resource.canonical for r in app.router.routes()
                    if r.method == "GET" and "{" not in r.resource.canonical and "static" not in r.resource.canonical})
    assert "/dashboard/" in paths and "/api/v1/status" in paths and "/dashboard/data/overview" in paths
    async with TestClient(TestServer(app)) as client:
        r = await client.post("/login", data={"username": "admin", "password": cfg.dashboard_pwd, "next": ""}, allow_redirects=False)
        assert r.status == 302
        bad = []
        for p in paths:
            if p in ("/logout", "/login"):
                continue
            resp = await client.get(p, headers={"Authorization": "Bearer " + cfg.api_key})
            if resp.status >= 500:
                bad.append((p, resp.status))
        assert bad == []
        body = await (await client.get("/dashboard/data/overview")).json()
    assert body["collector"]["stale"] is False and body["collector"]["age_sec"] < 30
