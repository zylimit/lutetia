"""IoT, summary and status resources of /api/v1 (manholes, fall events, bundles, collector status). All GET, all read-only.
POI resources are in pois.py. Handlers parse the request, call lutetia.queries_v1 and shape the public fields."""
from typing import Any, Dict, List, Optional, Tuple

from aiohttp import web

from ... import queries_v1 as q
from ..callers import API_SCOPES
from ..auth import require_api
from ..data import MAP_TRACK_BUCKET_SEC, heartbeat_view
from ..embed import EMBED_ORIGINS
from ..jsonutil import validate_device_id
from .envelope import (BadParam, NotFound, c_dt, c_int64, c_str, data_response, decode_cursor, errors_as_responses,
                       list_response, no_nul, now_utc, parse_days, parse_limit, parse_time)
from .pois import poi_summary_block

MANHOLE_FIELDS = ("device_id", "name", "status", "open_event", "volt", "rsrp", "last_seen", "lat", "lon", "location_verified")
BUNDLE_FIELDS = ("device_id", "name", "lat", "lon", "at", "moving", "online")


def _pick(row: Dict[str, Any], fields: Tuple[str, ...]) -> Dict[str, Any]:
    return {k: row[k] for k in fields}


def _page_after(rows: List[Dict[str, Any]], after_id: Optional[str], limit: int, resume_by_id: bool) -> Tuple[List[Dict[str, Any]], Optional[Tuple[str]]]:
    """Page of rows (sorted) after the item whose device_id the cursor carries. The cursor holds only the id, never a name, so
    it stays short however long names get. resume_by_id: the sort order is by name, so the id's position is looked up in the
    current list (an id that is no longer listed is a bad cursor); otherwise the list is sorted by id itself."""
    start = 0
    if after_id is not None:
        if resume_by_id:
            at = next((i for i, r in enumerate(rows) if r["device_id"] == after_id), None)
            if at is None:
                raise BadParam("invalid cursor")
            start = at + 1
        else:
            start = next((i for i, r in enumerate(rows) if r["device_id"] > after_id), len(rows))
    page = rows[start:start + limit]
    return page, ((page[-1]["device_id"],) if start + limit < len(rows) else None)


@require_api("iot:read")
@errors_as_responses
async def summary(request: web.Request) -> web.Response:
    db, now = request.app["ctx"].db, now_utc()
    mh = await q.manholes(db, now)
    counts = {s: sum(1 for m in mh if m["status"] == s) for s in q.STATUSES}
    in_use = len(mh) - counts["inactive"]
    bundles = await q.bundles(db, now)
    stamps = [b["at"] for b in bundles if b["at"] is not None]
    collector = heartbeat_view(await db.collector_status())[1]
    pois = await poi_summary_block(db) if "poi:read" in request.get(API_SCOPES, ()) else None
    return data_response({
        # in-use manholes (not inactive) fall in three mutually exclusive bands: moved_24h (includes moving) + offline + quiet == total;
        # inactive ones (expected_online false or unknown) are counted apart; all = total + inactive (Decisions 2026-11-09 / 2026-11-10)
        "manholes": {"total": in_use, "inactive": counts["inactive"], "all": len(mh),
                     "moved_24h": counts["moving"] + counts["moved"], "moving": counts["moving"],
                     "offline": counts["offline"], "offline_with_open_event": sum(1 for m in mh if m["status"] == "offline" and m["open_event"]),
                     "quiet": counts["quiet"]},
        "bundles": {"trackers": len(bundles), "online": sum(1 for b in bundles if b["online"]),
                    "last_position_at": max(stamps) if stamps else None},
        "pois": pois,
        "collector": {"updated_at": collector["updated_at"], "stale": collector["stale"]},
    }, now)


@require_api("iot:read")
@errors_as_responses
async def manholes(request: web.Request) -> web.Response:
    limit = parse_limit(request)
    after = decode_cursor(request, (c_str,))
    now = now_utc()
    page, nxt = _page_after(await q.manholes(request.app["ctx"].db, now), after[0] if after else None, limit, True)
    return list_response([_pick(m, MANHOLE_FIELDS) for m in page], now, nxt)


def _device_filter(request: web.Request) -> Optional[str]:
    dev = request.query.get("device_id")
    if dev is None or dev == "":
        return None
    no_nul("device_id", dev)
    err = validate_device_id(dev)
    if err:
        raise BadParam(err)
    return dev


@require_api("iot:read")
@errors_as_responses
async def fall_events(request: web.Request) -> web.Response:
    limit = parse_limit(request)
    since, until = parse_time("since", request.query.get("since")), parse_time("until", request.query.get("until"))
    if since is not None and until is not None and since > until:
        raise BadParam("since must not be after until")
    dev = _device_filter(request)
    after = decode_cursor(request, (c_dt, c_str))
    now = now_utc()
    rows = await q.fall_events(request.app["ctx"].db, since, until, dev, after, limit + 1)
    page = rows[:limit]
    nxt = [page[-1]["started_at"], page[-1]["device_id"]] if len(rows) > limit else None
    return list_response(page, now, nxt)


@require_api("iot:read")
@errors_as_responses
async def bundles(request: web.Request) -> web.Response:
    limit = parse_limit(request)
    after = decode_cursor(request, (c_str,))
    now = now_utc()
    page, nxt = _page_after(await q.bundles(request.app["ctx"].db, now), after[0] if after else None, limit, False)
    return list_response([_pick(b, BUNDLE_FIELDS) for b in page], now, nxt)


@require_api("iot:read")
@errors_as_responses
async def bundle_track(request: web.Request) -> web.Response:
    device_id = request.match_info["device_id"]
    err = validate_device_id(device_id)
    if err:
        raise BadParam(err)
    days = parse_days(request, 7, 1, 30)
    limit = parse_limit(request)
    after = decode_cursor(request, (c_int64,))
    db, now = request.app["ctx"].db, now_utc()
    if not await q.bundle_exists(db, device_id):
        raise NotFound("unknown bundle")
    rows = await q.track_page(db, device_id, days, MAP_TRACK_BUCKET_SEC, after[0] if after else None, limit + 1)
    page = rows[:limit]
    items = [{"at": r["update_time"], "lat": r["lat"], "lon": r["lon"], "speed_kmh": r["speed_kmh"],
              "moving": None if r["moving"] is None else bool(r["moving"])} for r in page]  # newest first
    return list_response(items, now, [page[-1]["bucket"]] if len(rows) > limit else None)


async def embed_config(request: web.Request) -> web.Response:
    """The origin patterns allowed to frame /embed/* (Phase 12, THR-3). No credential needed: a signed-out widget must still know
    whom it may talk to, and the list is the frame-ancestors of every /embed/<widget> answer anyway; it holds no data (OUT-12)."""
    return data_response({"origins": list(request.app[EMBED_ORIGINS])}, now_utc())


@require_api("status:read")
@errors_as_responses
async def collector_status(request: web.Request) -> web.Response:
    receiver, collector = heartbeat_view(await request.app["ctx"].db.collector_status())
    return data_response({"collector": collector, "receiver": receiver}, now_utc())
