"""Session-authenticated JSON data endpoints for the dashboard pages (read-only; the API key is never used here)."""
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from aiohttp import web

from ..db import max_age_hours
from . import anomalies
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


async def build_anomalies(ctx: object, now: datetime, devices: List[Dict], sensors: List[Dict], calls: List[Dict]) -> List[Dict]:
    return anomalies.compute(now, devices, sensors, await ctx.db.latest_alarm_values(anomalies.ALARM_KEYS), receiver_counts(ctx.receiver),  # type: ignore[attr-defined]
                             calls, ctx.cfg.gps51_daily_budget, ctx.cfg.low_volt,  # type: ignore[attr-defined]
                             push_silent_limit_sec=ctx.cfg.push_silence_min * 60)  # type: ignore[attr-defined]


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
    sensors = await ctx.db.latest_sensor_values(DEFAULT_KEYS)
    calls = await ctx.db.call_summary(24)
    items = await build_anomalies(ctx, now, devices, sensors, calls)
    return _json({
        "generated_at": now,
        "devices": devices,
        "latest_sensor": sensors,
        "latest_gps": await ctx.db.latest_gps_positions(),
        "receiver": receiver_counts(ctx.receiver),
        "api_calls_24h": calls,
        "anomalies": items,
        "anomaly_summary": anomalies.summarize(items),
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


MAP_TRACK_DAYS = 7
MAP_TRACK_LIMIT = 500


async def _gps_entries(db: object, status: List[Dict], with_tracks: bool) -> List[Dict]:
    latest = {r["device_id"]: r for r in await db.latest_gps_positions()}  # type: ignore[attr-defined]
    names = {r["device_id"]: r["name"] for r in status if r["source"] == "gps51"}
    out: List[Dict] = []
    for dev in list(names) + [d for d in latest if d not in names]:
        p = latest.get(dev)
        track: List = []
        if with_tracks and p is not None:
            rows = await db.positions_recent(dev, MAP_TRACK_DAYS, MAP_TRACK_LIMIT)  # type: ignore[attr-defined]
            track = [[r["lat"], r["lon"]] for r in reversed(rows)]  # newest first from db
        out.append({"device_id": dev, "name": names.get(dev) or (p or {}).get("name") or dev,
                    "lat": p["lat"] if p else None, "lon": p["lon"] if p else None,
                    "update_time": p["update_time"] if p else None, "speed_kmh": p["speed_kmh"] if p else None,
                    "moving": p["moving"] if p else None, "total_distance_km": p["total_distance_km"] if p else None,
                    "track": track})
    return out


@require_session_json
async def map_data(request: web.Request) -> web.Response:
    days = request.query.get("days", "0")
    if days not in ("0", "7"):
        return _bad("days must be 0 or 7")
    db = request.app["ctx"].db
    now = datetime.now(timezone.utc)
    status = await db.device_status()
    last = {r["device_id"]: r["last_ts"] for r in status}
    vals: Dict[str, Dict] = {}
    for r in await db.latest_sensor_values(("volt", "temperature")):
        vals.setdefault(r["device_id"], {})[r["key"]] = r["value_si"]
    manholes = [{"device_id": m["device_id"], "name": m["name"] or m["device_id"], "lat": m["lat"], "lon": m["lon"],
                 "last_ts": last.get(m["device_id"]), "volt": vals.get(m["device_id"], {}).get("volt"),
                 "temperature": vals.get(m["device_id"], {}).get("temperature")} for m in await db.manhole_locations()]
    return _json({"generated_at": now, "gps": await _gps_entries(db, status, days == "7"), "manholes": manholes})


def register_data(app: web.Application) -> None:
    app.router.add_get("/dashboard/data/overview", overview)
    app.router.add_get("/dashboard/data/telemetry", telemetry)
    app.router.add_get("/dashboard/data/positions", positions)
    app.router.add_get("/dashboard/data/map", map_data)
