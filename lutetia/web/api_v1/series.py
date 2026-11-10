"""GET /api/v1/manholes/{device_id}/series: voltage and signal series for the project dashboard's manhole drawer (Task 9.3).
Added because the legacy /api/v1/telemetry (unchanged) cannot average by hour and caps at 10000 rows. Read-only, iot:read.
7 days = raw readings, 30 days = hourly averages (the same Database.telemetry_series the ops device page uses)."""
from typing import Any, Dict, List

from aiohttp import web

from ... import queries_v1 as q
from ..auth import require_api
from ..data import SERIES_MAX_POINTS
from ..jsonutil import validate_device_id
from .envelope import BadParam, NotFound, data_response, errors_as_responses, now_utc

SERIES_KEYS = ("volt", "rsrp")
SERIES_DAYS = ("7", "30")


@require_api("iot:read")
@errors_as_responses
async def manhole_series(request: web.Request) -> web.Response:
    device_id = request.match_info["device_id"]
    err = validate_device_id(device_id)
    if err:
        raise BadParam(err)
    raw = request.query.get("days", "7")
    if raw not in SERIES_DAYS:
        raise BadParam("days must be 7 or 30")
    days = int(raw)
    db, now = request.app["ctx"].db, now_utc()
    if not await q.manhole_exists(db, device_id):
        raise NotFound("unknown manhole")
    rows = await db.telemetry_series(device_id, SERIES_KEYS, days, days == 30)  # oldest first, up to 1501 per key
    series: Dict[str, List[Dict[str, Any]]] = {k: [] for k in SERIES_KEYS}
    for r in rows:
        series[r["key"]].append({"at": r["ts"], "value": None if r["value_si"] is None else float(r["value_si"])})
    truncated = any(len(v) > SERIES_MAX_POINTS for v in series.values())
    return data_response({"device_id": device_id, "days": days, "hourly": days == 30,
                          "volt": series["volt"][-SERIES_MAX_POINTS:], "rsrp": series["rsrp"][-SERIES_MAX_POINTS:],
                          "truncated": truncated}, now)
