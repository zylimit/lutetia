"""GPS51 (途强物联) source: openapi client with token cache and call budget, incremental poller,
and the HTTP receiver for the vendor's 数据转发 push."""
import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import web

from ..config import Config
from ..db import Database, is_transient_db_error
from ..models import Device
from ..parsers.gps51 import (is_alarm_message, parse_lastposition, parse_monitorlist, parse_push_payload,
                             parse_tracks, push_items)

log = logging.getLogger(__name__)

TOKEN_MAX_AGE = 23 * 3600          # vendor: token lives 24h, log in once per 23h
STATUS_TOKEN_EXPIRED = (9903, 9906)
STATUS_IP_RATE_LIMITED = 8902
RETRY_BACKOFF_START, RETRY_BACKOFF_MAX = 1.0, 30.0


class Gps51Error(Exception):
    pass


class BudgetExceeded(Gps51Error):
    pass


class Gps51Client:
    def __init__(self, cfg: Config, db: Database, session: aiohttp.ClientSession):
        self.cfg, self.db, self.session = cfg, db, session
        self.token_path = cfg.state_dir / "gps51_token.json"
        self._token: Optional[str] = None
        self._serverid: Optional[int] = None
        self._obtained_at = 0.0
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._login_failures = 0
        self._last_login_attempt = 0.0

    # --- auth --------------------------------------------------------------
    def _load_token(self) -> None:
        if not self.token_path.exists():
            return
        try:
            d = json.loads(self.token_path.read_text())
            self._token, self._serverid, self._obtained_at = d["token"], int(d["serverid"]), float(d["obtained_at"])
        except (ValueError, KeyError, OSError):
            self._token = None

    async def login(self) -> None:
        self.cfg.require("gps51_user", "gps51_pwd")
        if self._login_failures:
            wait = min(3600, 60 * 2 ** (self._login_failures - 1)) - (time.monotonic() - self._last_login_attempt)
            if wait > 0:
                raise Gps51Error("gps51 login backoff: retry in %ds" % int(wait + 0.999))
        self._last_login_attempt = time.monotonic()
        try:
            await self._do_login()
        except BudgetExceeded:
            raise
        except Gps51Error:
            self._login_failures += 1
            raise
        self._login_failures = 0

    async def _do_login(self) -> None:
        body = {"type": "USER", "from": "WEB", "username": self.cfg.gps51_user,
                "password": hashlib.md5(self.cfg.gps51_pwd.encode()).hexdigest(), "browser": "lutetia/0.1"}
        data = await self._post("login", body, auth=False)
        if data.get("status") != 0:
            raise Gps51Error("login failed: status=%s cause=%s" % (data.get("status"), data.get("cause")))
        self._token, self._serverid, self._obtained_at = data["token"], int(data["serverid"]), time.time()
        self.token_path.write_text(json.dumps({"token": self._token, "serverid": self._serverid,
                                               "obtained_at": self._obtained_at}))
        log.info("gps51 login ok, serverid=%s", self._serverid)

    async def ensure_token(self) -> None:
        if not self._token:
            self._load_token()
        if not self._token or time.time() - self._obtained_at > TOKEN_MAX_AGE:
            await self.login()

    # --- transport ---------------------------------------------------------
    async def _post(self, action: str, body: Dict[str, Any], auth: bool = True) -> Dict[str, Any]:
        async with self._lock:
            since = datetime.now(timezone.utc) - timedelta(hours=24)
            used = await self.db.api_calls_since("gps51", since)
            if used >= self.cfg.gps51_daily_budget:
                raise BudgetExceeded("gps51 daily budget reached: %d/%d" % (used, self.cfg.gps51_daily_budget))
            gap = self.cfg.gps51_min_call_gap - (time.monotonic() - self._last_call)
            if gap > 0:
                await asyncio.sleep(gap)
            url = "%s?action=%s" % (self.cfg.gps51_api_base, action)
            if auth:
                url += "&token=%s&serverid=%s" % (self._token, self._serverid)
            try:
                async with self.session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=60)) as r:
                    text = await r.text()
            except (asyncio.TimeoutError, aiohttp.ClientError) as e:
                await self.db.record_api_call("gps51", action, False)
                raise Gps51Error("%s: %s" % (action, type(e).__name__))
            finally:
                self._last_call = time.monotonic()
            try:
                data = json.loads(text)
            except ValueError:
                data = {"status": -1, "cause": "non-json response: " + text[:200]}
            await self.db.record_api_call("gps51", action, data.get("status") == 0)
            return data

    async def call(self, action: str, body: Dict[str, Any]) -> Dict[str, Any]:
        await self.ensure_token()
        data = await self._post(action, body)
        status = data.get("status")
        if status in STATUS_TOKEN_EXPIRED:
            log.warning("gps51 token rejected (%s), re-login", status)
            await self.login()
            data = await self._post(action, body)
            status = data.get("status")
        if status == STATUS_IP_RATE_LIMITED:
            log.warning("gps51 ip rate limited, sleeping 60s")
            await asyncio.sleep(60)
            data = await self._post(action, body)
            status = data.get("status")
        if status != 0:
            raise Gps51Error("%s: status=%s cause=%s" % (action, status, data.get("cause")))
        return data

    # --- actions -----------------------------------------------------------
    async def monitorlist(self) -> Dict[str, Any]:
        return await self.call("querymonitorlist", {"username": self.cfg.gps51_user})

    async def lastposition(self, last_query_time: int = 0, device_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        return await self.call("lastposition", {"username": self.cfg.gps51_user, "deviceids": device_ids or [],
                                                "lastquerypositiontime": last_query_time})

    async def querytracks(self, device_id: str, begin: str, end: str, tz: int = 8) -> Dict[str, Any]:
        """Manual use only: 5 calls per device per day, automated sync is forbidden by the vendor."""
        return await self.call("querytracks", {"deviceid": device_id, "begintime": begin, "endtime": end, "timezone": tz})


class Gps51Poller:
    def __init__(self, client: Gps51Client, db: Database):
        self.client, self.db = client, db
        self.last_query_time = 0
        self.polls = 0
        self.polling = False  # set by fallback_loop: True while in poll mode (push silent)

    async def sync_devices(self) -> List[Device]:
        devices = parse_monitorlist(await self.client.monitorlist())
        await self.db.upsert_devices(devices)
        log.info("gps51 devices synced: %d (%d expected online)", len(devices), sum(1 for d in devices if d.expected_online))
        return devices

    async def poll_once(self) -> int:
        resp = await self.client.lastposition(self.last_query_time)
        rows = parse_lastposition(resp)
        inserted = await self.db.insert_gps_positions(rows)
        self.last_query_time = int(resp.get("lastquerypositiontime") or self.last_query_time)  # only after the rows are stored
        self.polls += 1
        log.info("gps51 poll #%d: %d records, %d new", self.polls, len(rows), inserted)
        return inserted

    async def fetch_tracks(self, device_id: str, begin: str, end: str) -> int:
        rows = parse_tracks(await self.client.querytracks(device_id, begin, end))
        inserted = await self.db.insert_gps_positions(rows)
        log.info("gps51 tracks %s %s..%s: %d records, %d new", device_id, begin, end, len(rows), inserted)
        return inserted


class PushReceiver:
    """Accepts the vendor's forwarded JSON, answers 200 immediately, stores from a background queue."""

    def __init__(self, cfg: Config, db: Database):
        self.cfg, self.db = cfg, db
        self.queue: "asyncio.Queue[Any]" = asyncio.Queue()
        self.started_at = time.monotonic()
        self.last_push_at: Optional[float] = None
        self.last_position_at: Optional[float] = None
        self.last_position_wall: Optional[datetime] = None  # wall-clock twin of last_position_at, for the heartbeat row
        self.received = 0
        self.stored = 0
        self.rejected = 0
        self.unrecognised = 0
        self.alarms = 0
        self.failed = 0
        self.drain_timeout = 30.0
        self._runner: Optional[web.AppRunner] = None
        self._consumer: Optional[asyncio.Task] = None

    def silent_for(self) -> float:
        """Seconds since the last recognisable position message (what polling fallback watches)."""
        return time.monotonic() - (self.last_position_at or self.started_at)

    def message_silent_for(self) -> float:
        """Seconds since the last valid JSON body of any kind."""
        return time.monotonic() - (self.last_push_at or self.started_at)

    async def _handle(self, request: web.Request) -> web.Response:
        raw = await request.read()
        try:
            payload = json.loads(raw.decode("utf-8"))  # empty body raises ValueError too
        except (ValueError, UnicodeDecodeError):
            self.rejected += 1
            return web.json_response({"status": 1, "cause": "invalid json"}, status=400)
        self.received += 1
        self.last_push_at = time.monotonic()
        self.queue.put_nowait(payload)
        return web.json_response({"status": 0, "cause": "OK"})

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "received": self.received, "stored": self.stored,
                                  "rejected": self.rejected, "unrecognised": self.unrecognised,
                                  "alarms": self.alarms, "failed": self.failed, "queued": self.queue.qsize(),
                                  "silent_sec": int(self.silent_for()),
                                  "message_silent_sec": int(self.message_silent_for())})

    async def _store(self, payload: Any) -> None:
        alarm_items = [m for m in push_items(payload) if is_alarm_message(m)]
        for m in alarm_items:
            log.info("gps51 push: alarm message deviceid=%s stralarm=%s, counted not stored",
                     m.get("deviceid"), m.get("stralarm"))
        self.alarms += len(alarm_items)
        rows = parse_push_payload(payload)
        if rows:
            self.last_position_wall = datetime.now(timezone.utc)
            self.last_position_at = time.monotonic()  # before the write: a duplicate delivery still proves liveness
        else:
            if not alarm_items:
                self.unrecognised += 1
                keys = list(payload.keys())[:10] if isinstance(payload, dict) else type(payload).__name__
                log.warning("gps51 push: unrecognised payload, keys=%s", keys)
            return
        delay, attempt = RETRY_BACKOFF_START, 0
        while True:
            try:
                n = await self.db.insert_gps_positions(rows)
                break
            except Exception as e:
                if not is_transient_db_error(e):
                    raise
                attempt += 1
                log.warning("gps51 push: db write failed (%s), retry #%d in %ds", e, attempt, int(delay))
                await asyncio.sleep(delay)
                delay = min(delay * 2, RETRY_BACKOFF_MAX)
        self.stored += n
        log.info("gps51 push: %d positions, %d new", len(rows), n)

    async def _consume(self) -> None:
        while True:
            payload = await self.queue.get()
            try:
                await self._store(payload)
            except Exception:
                self.failed += 1
                log.exception("gps51 push: failed to store payload, dropped")
            finally:
                self.queue.task_done()

    async def start(self) -> None:
        app = web.Application(client_max_size=4 * 1024 * 1024)
        app.router.add_post(self.cfg.push_path, self._handle)
        app.router.add_get("/health", self._health)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.cfg.push_host, self.cfg.push_port).start()
        self._consumer = asyncio.create_task(self._consume())
        log.info("gps51 push receiver listening on %s:%d%s", self.cfg.push_host, self.cfg.push_port, self.cfg.push_path)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()  # no new requests
        if self._consumer:
            if self.queue.qsize():
                log.info("gps51 push: waiting for %d queued pushes", self.queue.qsize())
            try:
                await asyncio.wait_for(self.queue.join(), timeout=self.drain_timeout)
            except asyncio.TimeoutError:
                log.error("gps51 push: drain timed out after %.1fs, %d remaining pushes lost",
                          self.drain_timeout, self.queue.qsize() + 1)
            self._consumer.cancel()
            await asyncio.gather(self._consumer, return_exceptions=True)


async def fallback_loop(cfg: Config, poller: Gps51Poller, receiver: PushReceiver) -> None:
    """Polls lastposition only while the push channel has been silent longer than PUSH_SILENCE_MIN."""
    mode = "push"
    while True:
        await asyncio.sleep(cfg.gps51_poll_interval)
        silent = receiver.silent_for()
        if silent > cfg.push_silence_min * 60:
            if mode != "poll":
                log.warning("gps51 push silent for %.0f min -> polling every %ds", silent / 60, cfg.gps51_poll_interval)
                mode = "poll"
                poller.polling = True
            try:
                await poller.poll_once()
            except BudgetExceeded as e:
                log.error("%s; polling paused for 1h", e)
                poller.polling = False  # the heartbeat must not claim we are polling while paused
                await asyncio.sleep(3600)
                poller.polling = True
            except Exception:
                log.exception("gps51 poll failed")
        elif mode != "push":
            log.info("gps51 push resumed -> polling stopped")
            mode = "push"
            poller.polling = False
