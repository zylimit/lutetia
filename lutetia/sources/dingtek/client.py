"""Dingtek Cloud (ThingsBoard) REST client: JWT cache/refresh and login backoff."""
import asyncio
import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional

import aiohttp

from ...config import Config
from ...db import Database

log = logging.getLogger(__name__)

LOGIN_MIN_GAP = 15.0          # vendor: 5 logins per minute per IP
LOGIN_BACKOFF_MAX = 900.0
PAGE_LIMIT = 1000             # ThingsBoard per-key limit on values/timeseries


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
