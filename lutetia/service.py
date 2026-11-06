"""Long-running collector: GPS51 push receiver + silence-triggered polling, Dingtek WebSocket + daily reconcile."""
import asyncio
import logging
import signal
from datetime import datetime, timedelta, timezone

import aiohttp

from .config import Config
from .db import Database
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


async def run(cfg: Config) -> None:
    db = Database(cfg.database_url)
    await db.connect()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    async with aiohttp.ClientSession() as session:
        receiver = PushReceiver(cfg, db)
        poller = Gps51Poller(Gps51Client(cfg, db, session), db)
        dclient = DingtekClient(cfg, db, session)
        dsync = DingtekSync(dclient, db)
        tasks = []
        try:
            await receiver.start()
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
                    tasks.append(asyncio.create_task(DingtekWs(dclient, db, session, device_ids).run(), name="dingtek-ws"))
                tasks.append(asyncio.create_task(dingtek_reconcile_loop(cfg, dsync), name="dingtek-reconcile"))
            else:
                log.warning("DINGTEK_USER not set: dingtek source disabled")

            log.info("lutetia running with %d background tasks", len(tasks))
            await stop.wait()
            log.info("shutdown requested")
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await receiver.stop()
            await db.close()
