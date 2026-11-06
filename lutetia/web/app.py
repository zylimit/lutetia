"""Second HTTP listener: read-only dashboard (and query API). No write path lives under lutetia/web."""
import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from aiohttp import web

from ..config import Config
from ..db import Database
from .api import register_api
from .auth import LoginLimiter, SessionSigner
from .dashboard import register_dashboard

log = logging.getLogger(__name__)

LOOPBACK = ("127.0.0.1", "localhost", "::1")


@dataclass
class WebContext:
    cfg: Config
    db: Database
    receiver: Optional[Any]
    started_at: datetime
    signer: SessionSigner
    limiter: LoginLimiter


class WebServer:
    def __init__(self, cfg: Config, db: Database, receiver: Optional[Any], started_at: datetime):
        self.cfg, self.db, self.receiver, self.started_at = cfg, db, receiver, started_at
        self._runner: Optional[web.AppRunner] = None
        self.active = False

    def build_app(self) -> web.Application:
        secret = self.cfg.session_secret.encode("utf-8") if self.cfg.session_secret else secrets.token_bytes(32)
        secret = hashlib.sha256(secret + b"\x00" + self.cfg.dashboard_pwd.encode("utf-8")).digest()
        app = web.Application()
        app["ctx"] = WebContext(self.cfg, self.db, self.receiver, self.started_at,
                                SessionSigner(secret), LoginLimiter())
        register_dashboard(app)
        register_api(app)
        return app

    async def start(self) -> None:
        cfg = self.cfg
        if cfg.dashboard_host not in LOOPBACK and (not cfg.dashboard_pwd or not cfg.api_key):
            raise SystemExit("DASHBOARD_LISTEN_HOST is not loopback: set DASHBOARD_PWD and API_KEY")
        if not cfg.session_secret:
            log.warning("SESSION_SECRET not set: sessions are invalidated on every restart")
        runner = web.AppRunner(self.build_app())
        await runner.setup()
        try:
            await web.TCPSite(runner, cfg.dashboard_host, cfg.dashboard_port).start()
        except OSError as e:
            log.error("web ui failed to start on %s:%d: %s; collector continues without dashboard",
                      cfg.dashboard_host, cfg.dashboard_port, e)
            self.active = False
            await runner.cleanup()
            return
        self._runner = runner
        self.active = True
        log.info("web ui listening on %s:%d", cfg.dashboard_host, cfg.dashboard_port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        self.active = False
