"""Dingtek WebSocket live telemetry subscription with reconnect backoff."""
import asyncio
import json
import logging
import time
from typing import Dict, List, Optional

import aiohttp

from ...db import Database
from ...parsers.dingtek import parse_ws_message
from .client import DingtekClient, DingtekError

log = logging.getLogger(__name__)

WS_ERR_UNAUTHORIZED = 3
WS_BACKOFF_START = 5.0
WS_BACKOFF_MAX = 120.0
WS_STABLE_SESSION_S = 60.0    # a session shorter than this does not reset the reconnect backoff
WS_FRESH_TOKEN_S = 120.0      # errorCode=3 this soon after obtaining a token: re-login would not help


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
                    if time.monotonic() - self.client.token_obtained_at < WS_FRESH_TOKEN_S:
                        log.error("dingtek ws handshake %s right after obtaining a token; not re-logging in, backing off", e.status)
                    else:
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
