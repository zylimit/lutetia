"""Dingtek Cloud (ThingsBoard) source: REST client with JWT cache/refresh and login backoff,
history backfill with window splitting, WebSocket live subscription, daily reconcile."""
from .client import LOGIN_BACKOFF_MAX, LOGIN_MIN_GAP, PAGE_LIMIT, DingtekClient, DingtekError, _jwt_exp
from .sync import DAY_MS, MIN_WINDOW_MS, DingtekSync
from .ws import (WS_BACKOFF_MAX, WS_BACKOFF_START, WS_ERR_UNAUTHORIZED, WS_FRESH_TOKEN_S, WS_STABLE_SESSION_S,
                 DingtekWs)

__all__ = [
    "DingtekClient", "DingtekSync", "DingtekWs", "DingtekError", "_jwt_exp",
    "LOGIN_MIN_GAP", "LOGIN_BACKOFF_MAX", "PAGE_LIMIT", "DAY_MS", "MIN_WINDOW_MS",
    "WS_ERR_UNAUTHORIZED", "WS_BACKOFF_START", "WS_BACKOFF_MAX", "WS_STABLE_SESSION_S", "WS_FRESH_TOKEN_S",
]
