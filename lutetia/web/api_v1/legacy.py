"""The original four read-only resources (devices, positions, telemetry, status), moved here from lutetia/web/api.py
unchanged in path, fields, scope and error text. Their own limit rules (default 1000, max 10000) stay as they were."""
from datetime import datetime
from typing import Any, Optional, Tuple

from aiohttp import web

from ..auth import require_api
from ..data import heartbeat_view
from ..jsonutil import _dumps, validate_device_id
from .envelope import BadParam, parse_time as _parse_time

DEFAULT_LIMIT, MAX_LIMIT = 1000, 10000


def _json(obj: Any, status: int = 200) -> web.Response:
    return web.json_response(obj, status=status, dumps=_dumps)


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


@require_api("iot:read")
async def devices(request: web.Request) -> web.Response:
    return _json({"devices": await request.app["ctx"].db.list_devices()})


@require_api("iot:read")
async def positions(request: web.Request) -> web.Response:
    try:
        device_id, since, until, limit = _parse_common(request)
    except BadParam as e:
        return _bad(e)
    rows = await request.app["ctx"].db.query_positions(device_id, since, until, limit)
    return _json({"device_id": device_id, "count": len(rows), "positions": rows})


@require_api("iot:read")
async def telemetry(request: web.Request) -> web.Response:
    try:
        device_id, since, until, limit = _parse_common(request)
    except BadParam as e:
        return _bad(e)
    rows = await request.app["ctx"].db.query_telemetry(device_id, request.query.get("key") or None, since, until, limit)
    return _json({"device_id": device_id, "count": len(rows), "telemetry": rows})


@require_api("status:read")
async def status(request: web.Request) -> web.Response:
    ctx = request.app["ctx"]
    receiver, collector = heartbeat_view(await ctx.db.collector_status())
    # started_at = start time of this web process; the collector's own start time is collector.collector_started_at
    return _json({"started_at": ctx.started_at, "receiver": receiver, "collector": collector,
                  "api_calls_24h": await ctx.db.call_summary(24)})


def register_legacy(app: web.Application) -> None:
    app.router.add_get("/api/v1/devices", devices)
    app.router.add_get("/api/v1/positions", positions)
    app.router.add_get("/api/v1/telemetry", telemetry)
    app.router.add_get("/api/v1/status", status)
