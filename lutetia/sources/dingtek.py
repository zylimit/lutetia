"""Dingtek Cloud (ThingsBoard) source: REST client with JWT cache/refresh and login backoff,
history backfill with window splitting, WebSocket live subscription, daily reconcile."""
import asyncio
import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from ..config import Config
from ..db import Database
from ..models import Device
from ..parsers.dingtek import active_flag, parse_attributes, parse_devices, parse_timeseries, parse_ws_message

log = logging.getLogger(__name__)

LOGIN_MIN_GAP = 15.0          # vendor: 5 logins per minute per IP
LOGIN_BACKOFF_MAX = 900.0
PAGE_LIMIT = 1000             # ThingsBoard per-key limit on values/timeseries
DAY_MS = 86400000
MIN_WINDOW_MS = 15 * 60000
WS_ERR_UNAUTHORIZED = 3
WS_BACKOFF_START = 5.0
WS_BACKOFF_MAX = 120.0
WS_STABLE_SESSION_S = 60.0    # a session shorter than this does not reset the reconnect backoff
WS_FRESH_TOKEN_S = 120.0      # errorCode=3 this soon after obtaining a token: re-login would not help


class DingtekError(Exception):
    pass


def _jwt_exp(token: str) -> float:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return float(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
    except (IndexError, ValueError, TypeError):
        return 0.0


class DingtekClient:
    def __init__(self, cfg: Config, db: Database, session: aiohttp.ClientSession):
        self.cfg, self.db, self.session = cfg, db, session
        self.token_path = cfg.state_dir / "dingtek_token.json"
        self._token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._lock = asyncio.Lock()
        self._last_login_attempt = 0.0
        self._login_failures = 0
        self.token_obtained_at = 0.0      # time.monotonic() of last successful login/refresh; 0.0 = loaded from disk

    @property
    def token(self) -> Optional[str]:
        return self._token

    def _save(self) -> None:
        self.token_path.write_text(json.dumps({"token": self._token, "refreshToken": self._refresh_token}))

    def _load(self) -> None:
        if self.token_path.exists():
            try:
                d = json.loads(self.token_path.read_text())
                self._token, self._refresh_token = d.get("token"), d.get("refreshToken")
            except (ValueError, OSError):
                pass

    async def _login(self) -> None:
        self.cfg.require("dingtek_user", "dingtek_pwd")
        wait = LOGIN_MIN_GAP - (time.monotonic() - self._last_login_attempt)
        if self._login_failures:
            wait = max(wait, min(LOGIN_BACKOFF_MAX, LOGIN_MIN_GAP * 2 ** self._login_failures))
        if wait > 0:
            log.info("dingtek login throttled, waiting %.0fs", wait)
            await asyncio.sleep(wait)
        self._last_login_attempt = time.monotonic()
        async with self.session.post(self.cfg.dingtek_base + "/api/auth/login",
                                     json={"username": self.cfg.dingtek_user, "password": self.cfg.dingtek_pwd},
                                     timeout=aiohttp.ClientTimeout(total=30)) as r:
            text = await r.text()
            await self.db.record_api_call("dingtek", "login", r.status == 200)
            if r.status == 401:
                self._login_failures += 1
                raise DingtekError("dingtek login rejected (401): check credentials")
            if r.status != 200:
                self._login_failures += 1
                raise DingtekError("dingtek login failed: HTTP %d %s" % (r.status, text[:200]))
        d = json.loads(text)
        self._token, self._refresh_token, self._login_failures = d["token"], d.get("refreshToken"), 0
        self.token_obtained_at = time.monotonic()
        self._save()
        log.info("dingtek login ok, token exp in %.0f min", (_jwt_exp(self._token) - time.time()) / 60)

    async def _refresh(self) -> bool:
        if not self._refresh_token:
            return False
        async with self.session.post(self.cfg.dingtek_base + "/api/auth/token",
                                     json={"refreshToken": self._refresh_token},
                                     timeout=aiohttp.ClientTimeout(total=30)) as r:
            await self.db.record_api_call("dingtek", "refresh", r.status == 200)
            if r.status != 200:
                log.warning("dingtek token refresh failed: HTTP %d", r.status)
                return False
            d = await r.json()
        self._token, self._refresh_token = d["token"], d.get("refreshToken", self._refresh_token)
        self.token_obtained_at = time.monotonic()
        self._save()
        log.info("dingtek token refreshed")
        return True

    async def ensure_token(self) -> None:
        async with self._lock:
            if not self._token:
                self._load()
            if self._token and _jwt_exp(self._token) - time.time() > 300:
                return
            if not (self._token and await self._refresh()):
                await self._login()

    async def invalidate(self) -> None:
        async with self._lock:
            if not await self._refresh():
                await self._login()

    async def request(self, method: str, path: str, action: str, params: Optional[Dict[str, Any]] = None,
                      _retry: bool = True) -> Any:
        await self.ensure_token()
        async with self.session.request(method, self.cfg.dingtek_base + path, params=params,
                                        headers={"X-Authorization": "Bearer " + self._token, "Accept": "application/json"},
                                        timeout=aiohttp.ClientTimeout(total=120)) as r:
            text = await r.text()
            await self.db.record_api_call("dingtek", action, r.status == 200)
            if r.status == 401 and _retry:
                await self.invalidate()
                return await self.request(method, path, action, params, _retry=False)
            if r.status == 429 and _retry:
                log.warning("dingtek 429 on %s, backing off 30s", path)
                await asyncio.sleep(30)
                return await self.request(method, path, action, params, _retry=False)
            if r.status >= 400:
                raise DingtekError("%s %s: HTTP %d %s" % (method, path, r.status, text[:200]))
        return json.loads(text) if text else None

    # --- endpoints ---------------------------------------------------------
    async def list_devices(self) -> List[Dict[str, Any]]:
        out, page = [], 0
        while True:
            d = await self.request("GET", "/api/user/devices", "devices",
                                   {"pageSize": 100, "page": page, "sortProperty": "name"})
            out.extend(d.get("data") or [])
            if not d.get("hasNext"):
                return out
            page += 1

    async def ts_keys(self, uuid: str) -> List[str]:
        return await self.request("GET", "/api/plugins/telemetry/DEVICE/%s/keys/timeseries" % uuid, "keys") or []

    async def attributes(self, uuid: str) -> Any:
        return await self.request("GET", "/api/plugins/telemetry/DEVICE/%s/values/attributes" % uuid, "attributes")

    async def latest(self, uuid: str) -> Any:
        return await self.request("GET", "/api/plugins/telemetry/DEVICE/%s/values/timeseries" % uuid, "latest")

    async def timeseries(self, uuid: str, keys: List[str], start_ms: int, end_ms: int, limit: int = PAGE_LIMIT) -> Any:
        return await self.request("GET", "/api/plugins/telemetry/DEVICE/%s/values/timeseries" % uuid, "timeseries",
                                  {"keys": ",".join(keys), "startTs": start_ms, "endTs": end_ms, "limit": limit})


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
            except (DingtekError, aiohttp.ClientError, asyncio.TimeoutError) as e:
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


class DingtekWs:
    def __init__(self, client: DingtekClient, db: Database, session: aiohttp.ClientSession, device_ids: List[str]):
        self.client, self.db, self.session, self.device_ids = client, db, session, device_ids
        self.last_msg_at: Optional[float] = None
        self.stored = 0
        self.connections = 0

    async def _session_once(self) -> None:
        await self.client.ensure_token()
        url = self.client.cfg.dingtek_base.replace("https://", "wss://").replace("http://", "ws://")
        url += "/api/ws/plugins/telemetry?token=" + self.client.token
        sub_map: Dict[int, str] = {}
        cmds = []
        for i, uuid in enumerate(self.device_ids, start=1):
            cmds.append({"entityType": "DEVICE", "entityId": uuid, "scope": "LATEST_TELEMETRY", "cmdId": i})
            sub_map[i] = uuid
        async with self.session.ws_connect(url, heartbeat=30, timeout=30) as ws:
            self.connections += 1
            await ws.send_json({"tsSubCmds": cmds, "historyCmds": [], "attrSubCmds": []})
            log.info("dingtek ws connected, %d subscriptions", len(cmds))
            async for msg in ws:
                if msg.type != aiohttp.WSMsgType.TEXT:
                    if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
                    continue
                data = json.loads(msg.data)
                if data.get("errorCode"):
                    log.warning("dingtek ws error %s: %s", data.get("errorCode"), data.get("errorMsg"))
                    if data.get("errorCode") == WS_ERR_UNAUTHORIZED:
                        if time.monotonic() - self.client.token_obtained_at < WS_FRESH_TOKEN_S:
                            log.error("dingtek ws errorCode=3 right after obtaining a token; not re-logging in, backing off")
                        else:
                            await self.client.invalidate()
                        return
                    continue
                self.last_msg_at = time.monotonic()
                rows = parse_ws_message(data, sub_map)
                if rows:
                    n = await self.db.insert_telemetry(rows)
                    self.stored += n
                    if n:
                        log.info("dingtek ws: %s %d new values", sub_map.get(data.get("subscriptionId")), n)

    def _redact(self, text: str) -> str:
        tok = self.client.token
        return text.replace(tok, "<token>") if tok else text

    async def run(self) -> None:
        backoff = WS_BACKOFF_START
        while True:
            started = time.monotonic()
            try:
                await self._session_once()
                log.info("dingtek ws closed, reconnecting")
            except aiohttp.WSServerHandshakeError as e:
                log.warning("dingtek ws handshake failed: HTTP %s %s", e.status, e.message)   # str(e) carries the URL with ?token=
                if e.status in (401, 403):
                    try:
                        await self.client.invalidate()
                    except DingtekError as ie:
                        log.error("dingtek re-auth failed: %s", self._redact(str(ie)))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 - keep the ws loop alive; no traceback (it can embed the token URL)
                log.error("dingtek ws session failed: %s: %s", type(e).__name__, self._redact(str(e)))
            if time.monotonic() - started >= WS_STABLE_SESSION_S:
                backoff = WS_BACKOFF_START
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, WS_BACKOFF_MAX)
