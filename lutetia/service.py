"""Long-running service. Role collector: GPS51 push receiver + silence-triggered polling, Dingtek WebSocket + daily reconcile + heartbeat.
Role web: read-only dashboard / query API only (no receiver, no vendor calls, no heartbeat). Role all: both in one process (local dev)."""
import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

import aiohttp

from .config import Config
from .db import Database
from .heartbeat import heartbeat_loop
from .web import WebServer
from .sources.dingtek import DingtekClient, DingtekSync, DingtekWs
from .sources.gps51 import Gps51Client, Gps51Poller, PushReceiver, fallback_loop

log = logging.getLogger(__name__)


def _seconds_until(hour_utc: int) -> float:
    now = datetime.now(timezone.utc)
    target = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def dingtek_reconcile_loop(cfg: Config, sync: DingtekSync) -> None:
    while True:
        await asyncio.sleep(_seconds_until(cfg.dingtek_reconcile_hour_utc))
        try:
            await sync.reconcile()
        except Exception:
            log.exception("dingtek reconcile failed")


ROLES = ("collector", "web", "all")


async def _start_collector(cfg: Config, db: Database, session: aiohttp.ClientSession, tasks: list, held: dict,
                           on_listening: Optional[Callable[[], Awaitable[None]]] = None) -> Any:
    """Everything that talks to vendors or receives pushes. held["dws"] is filled once the Dingtek WebSocket exists."""
    receiver = PushReceiver(cfg, db)
    held["receiver"] = receiver  # visible to the caller's finally even if a later step raises
    poller = Gps51Poller(Gps51Client(cfg, db, session), db)
    dclient = DingtekClient(cfg, db, session)
    dsync = DingtekSync(dclient, db)
    await receiver.start()
    if on_listening is not None:
        await on_listening()  # role all: the dashboard comes up with the receiver, before the slow vendor syncs below
    # first heartbeat goes out now, before the (slow) startup syncs; dws is looked up at each beat
    tasks.append(asyncio.create_task(heartbeat_loop(db, receiver, poller, lambda: held.get("dws")), name="heartbeat"))
    if cfg.gps51_user:
        try:
            await poller.sync_devices()
        except Exception:
            log.exception("gps51 device sync failed at startup")
        tasks.append(asyncio.create_task(fallback_loop(cfg, poller, receiver), name="gps51-fallback"))
    else:
        log.warning("GPS51_USER not set: push receiver only, no polling")

    if cfg.dingtek_user:
        try:
            await dsync.reconcile()
        except Exception:
            log.exception("dingtek startup reconcile failed")
        device_ids = await db.list_device_ids("dingtek")
        if device_ids:
            held["dws"] = DingtekWs(dclient, db, session, device_ids)
            tasks.append(asyncio.create_task(held["dws"].run(), name="dingtek-ws"))
        tasks.append(asyncio.create_task(dingtek_reconcile_loop(cfg, dsync), name="dingtek-reconcile"))
    else:
        log.warning("DINGTEK_USER not set: dingtek source disabled")
    return receiver


async def run(cfg: Config, role: str = "all") -> None:
    if role not in ROLES:
        raise ValueError("unknown role %r, expected one of %s" % (role, "/".join(ROLES)))
    started_at = datetime.now(timezone.utc)
    db = Database(cfg.database_url)
    await db.connect()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    tasks: list = []
    held: dict = {}
    web_server = None
    session = None
    try:
        async def start_web() -> None:
            nonlocal web_server
            web_server = WebServer(cfg, db, started_at)
            await web_server.start()
            if role == "web" and not web_server.active:
                raise SystemExit("web role: dashboard failed to start, exiting")  # all-role keeps collecting without it; web-only has nothing else to do

        if role == "web":
            await start_web()
        else:
            session = aiohttp.ClientSession()
            # all: web starts right after the receiver, before the slow GPS51 / Dingtek startup syncs
            await _start_collector(cfg, db, session, tasks, held, start_web if role == "all" else None)
        log.info("lutetia running role=%s with %d background tasks", role, len(tasks))
        await stop.wait()
        log.info("shutdown requested")
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if held.get("receiver") is not None:
            await held["receiver"].stop()
        if web_server is not None:
            await web_server.stop()
        if session is not None:
            await session.close()
        await db.close()
