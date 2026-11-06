"""Session-authenticated JSON data endpoints for the dashboard pages (read-only; the API key is never used here)."""
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from aiohttp import web

from ..db import max_age_hours
from .auth import require_session_json
from .jsonutil import _dumps, validate_device_id

SERIES_MAX_POINTS = 1500
POSITIONS_LIMIT = 2000
DEFAULT_KEYS = ("volt", "temperature", "rsrp")
KEY_RE = re.compile(r"[A-Za-z0-9_]+")


def _json(obj: object, status: int = 200) -> web.Response:
    return web.json_response(obj, status=status, dumps=_dumps)


def _bad(msg: str) -> web.Response:
    return _json({"error": msg}, status=400)


def receiver_counts(rcv: object) -> object:
    if rcv is None:
        return None
    out = {k: getattr(rcv, k) for k in ("received", "stored", "rejected", "unrecognised", "alarms", "failed")}
    out["queued"] = rcv.queue.qsize() if hasattr(rcv, "queue") else getattr(rcv, "queued", 0)  # type: ignore[attr-defined]
    out["silent_sec"] = rcv.silent_for()  # type: ignore[attr-defined]
    out["message_silent_sec"] = rcv.message_silent_for()  # type: ignore[attr-defined]
    return out


@require_session_json
async def overview(request: web.Request) -> web.Response:
    ctx = request.app["ctx"]
    now = datetime.now(timezone.utc)
    devices: List[Dict] = []
    for r in await ctx.db.device_status():
        limit = max_age_hours(3.0, r["upload_interval_h"])
        last = r["last_ts"]
        stale = bool(r["expected_online"]) and (last is None or now - last > timedelta(hours=limit))
        devices.append(dict(r, stale=stale, max_age_h=limit))
    return _json({
        "generated_at": now,
        "devices": devices,
        "latest_sensor": await ctx.db.latest_sensor_values(DEFAULT_KEYS),
        "latest_gps": await ctx.db.latest_gps_positions(),
        "receiver": receiver_counts(ctx.receiver),
        "api_calls_24h": await ctx.db.call_summary(24),
        "anomalies": [],
    })


@require_session_json
async def telemetry(request: web.Request) -> web.Response:
    q = request.query
    device_id = q.get("device_id", "")
    if not device_id:
        return _bad("device_id required")
    err = validate_device_id(device_id)
    if err:
        return _bad(err)
    if q.get("days") not in ("7", "30"):
        return _bad("days must be 7 or 30")
    days = int(q["days"])
    keys = list(dict.fromkeys(q.get("keys", ",".join(DEFAULT_KEYS)).split(",")))  # order-preserving de-dup
    if len(keys) > 6 or not all(KEY_RE.fullmatch(k) for k in keys):
        return _bad("keys must be up to 6 comma-separated [A-Za-z0-9_] names")
    rows = await request.app["ctx"].db.telemetry_series(device_id, keys, days, days == 30)
    series: Dict[str, List] = {k: [] for k in keys}
    for r in rows:
        series[r["key"]].append([r["ts"], r["value_si"]])
    truncated = any(len(v) > SERIES_MAX_POINTS for v in series.values())
    series = {k: v[-SERIES_MAX_POINTS:] for k, v in series.items()}
    return _json({"device_id": device_id, "days": days, "hourly": days == 30, "series": series, "truncated": truncated})


@require_session_json
async def positions(request: web.Request) -> web.Response:
    q = request.query
    device_id = q.get("device_id", "")
    if not device_id:
        return _bad("device_id required")
    err = validate_device_id(device_id)
    if err:
        return _bad(err)
    try:
        days = int(q.get("days", "7"))
    except ValueError:
        return _bad("days must be an integer between 1 and 30")
    if days < 1 or days > 30:
        return _bad("days must be an integer between 1 and 30")
    rows = await request.app["ctx"].db.positions_recent(device_id, days, POSITIONS_LIMIT)
    return _json({"device_id": device_id, "days": days, "positions": rows})


def register_data(app: web.Application) -> None:
    app.router.add_get("/dashboard/data/overview", overview)
    app.router.add_get("/dashboard/data/telemetry", telemetry)
    app.router.add_get("/dashboard/data/positions", positions)
