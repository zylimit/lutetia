"""Second HTTP listener: read-only dashboard (and query API). No write path lives under lutetia/web."""
import logging
import secrets
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from aiohttp import web

from ..config import Config
from ..db import Database
from .api import register_api
from .auth import LoginLimiter, SessionSigner
from .callers import CallerRegistry, api_middleware
from .dashboard import register_dashboard
from .data import register_data
from .pages_device import register_device_pages
from .pages_map import register_map_pages

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data: https://mt0.google.com https://mt1.google.com https://mt2.google.com https://mt3.google.com; "
                               "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def _stamp(resp: web.StreamResponse) -> None:
    for name, value in SECURITY_HEADERS.items():
        resp.headers[name] = value


@web.middleware
async def security_headers(request: web.Request, handler: Any) -> web.StreamResponse:
    try:
        resp = await handler(request)
    except web.HTTPException as exc:  # redirects, 404 / 405 raised as exceptions are responses too
        resp = exc
    except Exception:
        log.exception("unhandled error on %s %s", request.method, request.path)
        resp = web.json_response({"error": "internal error"}, status=500)
    _stamp(resp)
    return resp


@dataclass
class WebContext:
    cfg: Config
    db: Database
    started_at: datetime
    signer: SessionSigner
    limiter: LoginLimiter
    callers: CallerRegistry


class WebServer:
    def __init__(self, cfg: Config, db: Database, started_at: datetime):
        self.cfg, self.db, self.started_at = cfg, db, started_at
        self._runner: Optional[web.AppRunner] = None
        self.active = False

    def build_app(self) -> web.Application:
        secret = self.cfg.session_secret.encode("utf-8") if self.cfg.session_secret else secrets.token_bytes(32)
        app = web.Application(middlewares=[security_headers, api_middleware])
        app["ctx"] = WebContext(self.cfg, self.db, self.started_at,
                                SessionSigner(secret, self.cfg.accounts()), LoginLimiter(enabled=self.cfg.login_lockout),
                                CallerRegistry.from_config(self.cfg))
        register_dashboard(app)
        register_api(app)
        register_data(app)
        register_device_pages(app)
        register_map_pages(app)
        app.router.add_static("/static/", STATIC_DIR, show_index=False, follow_symlinks=False)
        return app

    async def start(self) -> None:
        cfg = self.cfg
        accounts = cfg.accounts()  # duplicate names -> SystemExit
        if cfg.dashboard_host not in LOOPBACK and (not cfg.dashboard_pwd or not cfg.api_key):
            raise SystemExit("DASHBOARD_LISTEN_HOST is not loopback: set DASHBOARD_PWD and API_KEY")
        if not cfg.session_secret:
            log.warning("SESSION_SECRET not set: a random key is used, so all sessions (including 30-day ones) are lost on restart; set SESSION_SECRET in production")
        log.info("web accounts enabled: %s", ", ".join(sorted(accounts)) or "none")
        runner = web.AppRunner(self.build_app())
        await runner.setup()
        try:
            await web.TCPSite(runner, cfg.dashboard_host, cfg.dashboard_port).start()
        except OSError as e:
            log.error("web ui failed to start on %s:%d: %s; the process continues without dashboard unless role=web",
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
