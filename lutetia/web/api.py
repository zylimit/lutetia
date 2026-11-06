"""Read-only JSON query API (Bearer API key). GET only: nothing here writes to the database."""
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from aiohttp import web

from ..db import ms_to_dt
from .auth import require_api_key
from .jsonutil import _dumps, validate_device_id

DEFAULT_LIMIT, MAX_LIMIT = 1000, 10000


class BadParam(Exception):
    pass


def _json(obj: Any, status: int = 200) -> web.Response:
    return web.json_response(obj, status=status, dumps=_dumps)


def _parse_time(name: str, raw: Optional[str]) -> Optional[datetime]:
    if raw is None or raw == "":
        return None
    try:
        raw = raw.replace(" ", "+")  # an unencoded "+" in a query string arrives as a space
        if raw.lstrip("-").isdigit():
            return ms_to_dt(int(raw))
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        raise BadParam("%s must be ISO 8601 or epoch milliseconds" % name)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_common(request: web.Request) -> Tuple[str, Optional[datetime], Optional[datetime], int]:
    q = request.query
    device_id = q.get("device_id", "")
    if not device_id:
        raise BadParam("device_id required")
    err = validate_device_id(device_id)
    if err:
        raise BadParam(err)
    try:
        limit = int(q.get("limit", DEFAULT_LIMIT))
    except ValueError:
        raise BadParam("limit must be an integer")
    if limit < 1 or limit > MAX_LIMIT:
        raise BadParam("limit must be between 1 and %d" % MAX_LIMIT)
    return device_id, _parse_time("since", q.get("since")), _parse_time("until", q.get("until")), limit


def _bad(e: BadParam) -> web.Response:
    return _json({"error": str(e)}, status=400)


@require_api_key
async def devices(request: web.Request) -> web.Response:
    return _json({"devices": await request.app["ctx"].db.list_devices()})


@require_api_key
async def positions(request: web.Request) -> web.Response:
    try:
        device_id, since, until, limit = _parse_common(request)
    except BadParam as e:
        return _bad(e)
    rows = await request.app["ctx"].db.query_positions(device_id, since, until, limit)
    return _json({"device_id": device_id, "count": len(rows), "positions": rows})


@require_api_key
async def telemetry(request: web.Request) -> web.Response:
    try:
        device_id, since, until, limit = _parse_common(request)
    except BadParam as e:
        return _bad(e)
    rows = await request.app["ctx"].db.query_telemetry(device_id, request.query.get("key") or None, since, until, limit)
    return _json({"device_id": device_id, "count": len(rows), "telemetry": rows})


@require_api_key
async def status(request: web.Request) -> web.Response:
    ctx = request.app["ctx"]
    rcv = ctx.receiver
    receiver = None
    if rcv is not None:
        receiver = {k: getattr(rcv, k) for k in ("received", "stored", "rejected", "unrecognised", "alarms", "failed")}
        receiver["queued"] = rcv.queue.qsize() if hasattr(rcv, "queue") else getattr(rcv, "queued", 0)
        receiver["silent_sec"] = rcv.silent_for()
        receiver["message_silent_sec"] = rcv.message_silent_for()
    return _json({"started_at": ctx.started_at, "receiver": receiver,
                  "api_calls_24h": await ctx.db.call_summary(24)})


def register_api(app: web.Application) -> None:
    app.router.add_get("/api/v1/devices", devices)
    app.router.add_get("/api/v1/positions", positions)
    app.router.add_get("/api/v1/telemetry", telemetry)
    app.router.add_get("/api/v1/status", status)
