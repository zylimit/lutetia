# risk: high
"""Phase 7 Task 7.3: `lutetia run --role collector|web|all` starts only its own parts (ADR-1).
web 角色不得构造接收端 / 厂家客户端 / 心跳（那些要写库或碰厂家账号）；collector 角色不得起 WebServer。
所有组件用替身，不连库、不碰网络。"""
import asyncio
import dataclasses
import os
import signal

import pytest

from lutetia import cli, service
from lutetia.config import Config


class Rec:
    """Records which components were constructed / started / stopped."""
    built: list = []
    started: list = []
    stopped: list = []
    events: list = []  # ordered: construct:X / start:X / call:X / task:X


def make_fake(name, has_start=True):
    class Fake:
        def __init__(self, *a, **kw):
            Rec.built.append(name)
            Rec.events.append("construct:" + name)
            self.active = True
            self.polling = False
            self.connected = False

        async def start(self):
            Rec.started.append(name)
            Rec.events.append("start:" + name)

        async def stop(self):
            Rec.stopped.append(name)

        async def sync_devices(self):
            Rec.events.append("call:sync_devices")
            return []

        async def reconcile(self):
            Rec.events.append("call:reconcile")
            return 0

        async def run(self):
            await asyncio.sleep(3600)
    Fake.__name__ = name
    return Fake


class FakeDb:
    def __init__(self, url):
        Rec.built.append("Database")

    async def connect(self):
        pass

    async def close(self):
        pass

    async def list_device_ids(self, source):
        return ["d1"]

    async def migrate(self, *a, **kw):
        Rec.events.append("call:migrate")
        return []


def make_loop(name):
    async def loop(*a, **kw):
        Rec.events.append("task:" + name)
        await asyncio.sleep(3600)
    return loop


@pytest.fixture
def patched(monkeypatch):
    Rec.built, Rec.started, Rec.stopped, Rec.events = [], [], [], []
    monkeypatch.setattr(service, "Database", FakeDb)
    for name in ("PushReceiver", "Gps51Client", "Gps51Poller", "DingtekClient", "DingtekSync", "DingtekWs", "WebServer"):
        monkeypatch.setattr(service, name, make_fake(name))
    for name in ("heartbeat_loop", "fallback_loop", "dingtek_reconcile_loop"):
        monkeypatch.setattr(service, name, make_loop(name))
    cfg = dataclasses.replace(Config.from_env(), database_url="postgresql://x:x@127.0.0.1:1/x", gps51_user="u", dingtek_user="u")
    return cfg


async def run_briefly(cfg, role):
    asyncio.get_running_loop().call_later(0.3, os.kill, os.getpid(), signal.SIGTERM)
    await asyncio.wait_for(service.run(cfg, role), timeout=10)


COLLECTOR_PARTS = {"PushReceiver", "Gps51Client", "Gps51Poller", "DingtekClient", "DingtekSync", "DingtekWs"}


async def test_web_role_builds_only_web(patched):
    await run_briefly(patched, "web")
    assert set(Rec.built) == {"Database", "WebServer"}
    assert Rec.started == ["WebServer"] and Rec.stopped == ["WebServer"]
    # ADR-1: web is read-only — no heartbeat / vendor sync / migrate / background task of any kind
    assert Rec.events == ["construct:WebServer", "start:WebServer"]
    assert not {"task:heartbeat_loop", "call:migrate", "construct:PushReceiver"} & set(Rec.events)
    assert not any(n.startswith(("Gps51", "Dingtek")) for n in Rec.built)


async def test_collector_role_never_builds_web(patched):
    await run_briefly(patched, "collector")
    assert "WebServer" not in Rec.built
    assert COLLECTOR_PARTS <= set(Rec.built)
    assert Rec.started == ["PushReceiver"] and Rec.stopped == ["PushReceiver"]
    assert "task:heartbeat_loop" in Rec.events  # collector owns the heartbeat
    assert not any(e.endswith("WebServer") for e in Rec.events)


async def test_all_role_builds_both(patched):
    await run_briefly(patched, "all")
    assert COLLECTOR_PARTS | {"WebServer", "Database"} <= set(Rec.built)
    assert set(Rec.started) == {"PushReceiver", "WebServer"}
    assert "task:heartbeat_loop" in Rec.events and "call:migrate" not in Rec.events


async def test_all_role_web_starts_before_slow_syncs(patched):
    await run_briefly(patched, "all")
    ev = Rec.events
    web = ev.index("start:WebServer")
    assert ev.index("start:PushReceiver") < web
    assert web < ev.index("call:sync_devices") and web < ev.index("call:reconcile")


async def test_web_role_exits_when_dashboard_cannot_start(patched, monkeypatch):
    class Dead(make_fake("WebServer")):
        async def start(self):
            self.active = False
    monkeypatch.setattr(service, "WebServer", Dead)
    with pytest.raises(SystemExit):
        await asyncio.wait_for(service.run(patched, "web"), timeout=10)


async def test_unknown_role_rejected(patched):
    with pytest.raises(ValueError):
        await service.run(patched, "bogus")
    assert Rec.built == []


def test_run_role_arg_parsing():
    p = cli.build_parser()
    assert p.parse_args(["run"]).role == "all"
    assert p.parse_args(["run", "--role", "web"]).role == "web"
    assert p.parse_args(["run", "--role", "collector"]).role == "collector"
    with pytest.raises(SystemExit):
        p.parse_args(["run", "--role", "bogus"])


async def test_cmd_run_passes_role(monkeypatch):
    seen = []

    async def fake_run(cfg, role):
        seen.append(role)
    monkeypatch.setattr(service, "run", fake_run)
    args = cli.build_parser().parse_args(["run", "--role", "web"])
    assert await args.fn(None, args) == 0
    assert seen == ["web"]
