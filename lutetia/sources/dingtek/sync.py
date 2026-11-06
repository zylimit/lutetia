"""Dingtek history backfill with window splitting and daily reconcile."""
import asyncio
import logging
import time
from typing import List, Optional, Tuple

import aiohttp

from ...db import Database
from ...models import Device
from ...parsers.dingtek import active_flag, parse_attributes, parse_devices, parse_timeseries
from .client import PAGE_LIMIT, DingtekClient, DingtekError

log = logging.getLogger(__name__)

DAY_MS = 86400000
MIN_WINDOW_MS = 15 * 60000


class DingtekSync:
    def __init__(self, client: DingtekClient, db: Database):
        self.client, self.db = client, db
        self.last_failures: List[Tuple[str, str, str]] = []   # (uuid, name, error) of the last backfill

    async def sync_devices(self) -> List[Device]:
        devices = parse_devices({"data": await self.client.list_devices()})
        await self.db.upsert_devices(devices)
        log.info("dingtek devices synced: %d", len(devices))
        return devices

    async def refresh_attributes(self, uuid: str) -> Optional[bool]:
        attrs = parse_attributes(uuid, await self.client.attributes(uuid))
        await self.db.upsert_attributes(attrs)
        flag = active_flag(attrs)
        await self.db.set_expected_online("dingtek", uuid, flag)
        return flag

    async def _backfill_window(self, uuid: str, keys: List[str], start_ms: int, end_ms: int) -> int:
        resp = await self.client.timeseries(uuid, keys, start_ms, end_ms)
        rows = parse_timeseries(uuid, resp, origin="rest")
        saturated = isinstance(resp, dict) and any(len(v or []) >= PAGE_LIMIT for v in resp.values())
        if saturated and end_ms - start_ms > MIN_WINDOW_MS:
            mid = (start_ms + end_ms) // 2       # a key hit the page limit: split and refetch both halves
            return await self._backfill_window(uuid, keys, start_ms, mid) + await self._backfill_window(uuid, keys, mid + 1, end_ms)
        return await self.db.insert_telemetry(rows)

    async def backfill_device(self, uuid: str, start_ms: int, end_ms: int) -> int:
        keys = await self.client.ts_keys(uuid)
        if not keys:
            return 0
        total, cursor = 0, start_ms
        while cursor < end_ms:
            window_end = min(cursor + DAY_MS - 1, end_ms)
            total += await self._backfill_window(uuid, keys, cursor, window_end)
            cursor = window_end + 1
        return total

    async def backfill(self, start_ms: int, end_ms: Optional[int] = None) -> int:
        end_ms = end_ms or int(time.time() * 1000)
        total = 0
        self.last_failures = []
        devices = await self.sync_devices()
        for d in devices:
            try:
                n = await self.backfill_device(d.device_id, start_ms, end_ms)
                flag = await self.refresh_attributes(d.device_id)
            except (DingtekError, aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
                log.exception("dingtek backfill %s (%s) failed", d.name, d.device_id)
                self.last_failures.append((d.device_id, d.name or "", "%s: %s" % (type(e).__name__, e)))
                continue
            total += n
            log.info("dingtek backfill %s (%s): %d new rows, active=%s", d.name, d.device_id, n, flag)
        log.info("dingtek backfill done: %d new rows, %d/%d devices failed", total, len(self.last_failures), len(devices))
        return total

    async def reconcile(self, days: int = 2) -> int:
        """Re-pulls the last N days over REST to fill WebSocket gaps and refreshes attributes."""
        now = int(time.time() * 1000)
        n = await self.backfill(now - days * DAY_MS, now)
        log.info("dingtek reconcile: %d rows added", n)
        return n
