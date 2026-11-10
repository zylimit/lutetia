"""Read queries behind the /api/v1 resources. SELECT only, every value a bound parameter (the one dynamic part, the POI
filter, is assembled from fixed fragments). Rows come back as plain dicts; shaping into the public fields happens in
lutetia/web/api_v1. Manhole and bundle lists are composed from the Database methods the dashboard already uses, so the
two readers cannot disagree."""
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .db import Database, device_stale

STATUSES = ("inactive", "offline", "moving", "moved", "quiet")  # priority order, first match wins
MOVED_WINDOW = timedelta(hours=24)


async def event_flags(db: Database, now: datetime) -> Dict[str, bool]:
    """device_id -> True when the device has an unfinished fall event, False when its latest event ended inside the last 24 h.
    Devices with neither are absent."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT device_id, bool_or(ended_at IS NULL) AS moving FROM fall_event "
            "WHERE ended_at IS NULL OR ended_at >= $1 GROUP BY device_id", now - MOVED_WINDOW)
    return {r["device_id"]: bool(r["moving"]) for r in rows}


def classify(expected_online: Optional[bool], stale: bool, flags: Dict[str, bool], device_id: str) -> str:
    """inactive first (progress Decisions 2026-11-10: expected_online false or unknown means nobody is watching it, so it is
    not "quiet" and takes no part in the other bands); then offline, which stays offline even with an unfinished event
    (that combination is reported separately as open_event)."""
    if expected_online is not True:
        return "inactive"
    if stale:
        return "offline"
    if device_id in flags:
        return "moving" if flags[device_id] else "moved"
    return "quiet"


async def manholes(db: Database, now: datetime) -> List[Dict[str, Any]]:
    """One row per Dingtek device, sorted by (name or device_id, device_id). open_event = has an unfinished fall event, whatever the status."""
    flags = await event_flags(db, now)
    vals: Dict[str, Dict[str, Any]] = {}
    for r in await db.latest_sensor_values(("volt", "rsrp")):
        vals.setdefault(r["device_id"], {})[r["key"]] = r["value_si"]
    where = {m["device_id"]: m for m in await db.manhole_locations()}
    out: List[Dict[str, Any]] = []
    for r in await db.device_status():
        if r["source"] != "dingtek":
            continue
        dev = r["device_id"]
        stale, _ = device_stale(r, now)
        loc = where.get(dev)
        out.append({"device_id": dev, "name": r["name"], "status": classify(r["expected_online"], stale, flags, dev),
                    "open_event": flags.get(dev) is True,
                    "volt": vals.get(dev, {}).get("volt"), "rsrp": vals.get(dev, {}).get("rsrp"),
                    "last_seen": r["last_ts"], "lat": loc["lat"] if loc else None, "lon": loc["lon"] if loc else None,
                    "location_verified": False})
    out.sort(key=lambda m: (m["name"] or m["device_id"], m["device_id"]))
    return out


async def bundles(db: Database, now: datetime) -> List[Dict[str, Any]]:
    """One row per GPS51 device, sorted by device_id: every device with a position (gps_position is the main table, so a
    tracker whose push arrived before it was registered is listed) plus every registered one without, which is what the
    ops overview's map data lists too. online = expected online (or unknown) and the last position is within the same
    silence limit the dashboard uses for stale devices."""
    latest = {r["device_id"]: r for r in await db.latest_gps_positions()}
    registered = {r["device_id"]: r for r in await db.device_status() if r["source"] == "gps51"}
    out: List[Dict[str, Any]] = []
    for dev in sorted(set(latest) | set(registered)):
        p = latest.get(dev)
        # unregistered: no name, expected_online unknown, never configured with an uploadInterval
        r = registered.get(dev) or {"name": None, "expected_online": None, "upload_interval_h": None,
                                    "last_ts": p["update_time"] if p else None}
        last = r["last_ts"]
        _, limit = device_stale(r, now)
        out.append({"device_id": dev, "name": r["name"], "lat": p["lat"] if p else None, "lon": p["lon"] if p else None,
                    "at": p["update_time"] if p else None,
                    "moving": None if p is None or p["moving"] is None else bool(p["moving"]),
                    "online": r["expected_online"] is not False and last is not None and now - last <= timedelta(hours=limit)})
    return out


async def bundle_exists(db: Database, device_id: str) -> bool:
    """A tracker exists when it has positions or is registered as gps51 (same union as bundles())."""
    async with db.pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM gps_position WHERE device_id = $1) "
            "OR EXISTS (SELECT 1 FROM device WHERE source = 'gps51' AND device_id = $1)", device_id))


async def manhole_exists(db: Database, device_id: str) -> bool:
    """A manhole is a registered Dingtek device (the same set manholes() lists)."""
    async with db.pool.acquire() as conn:
        return bool(await conn.fetchval("SELECT EXISTS (SELECT 1 FROM device WHERE source = 'dingtek' AND device_id = $1)", device_id))


async def track_page(db: Database, device_id: str, days: int, bucket_sec: int, before_bucket: Optional[int],
                     limit: int) -> List[Dict[str, Any]]:
    """Same thinning as the map (one newest point per bucket_sec bucket; the caller passes the map's MAP_TRACK_BUCKET_SEC), newest first, keyset on the bucket number."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (bucket) bucket, update_time, lat, lon, speed_kmh, moving
            FROM (
                SELECT floor(extract(epoch FROM update_time) / $3::int)::bigint AS bucket, update_time, lat, lon, speed_kmh, moving
                FROM gps_position_v
                WHERE device_id = $1 AND update_time >= now() - make_interval(days => $2)
                  AND lat IS NOT NULL AND lon IS NOT NULL
            ) s
            WHERE $4::bigint IS NULL OR bucket < $4
            ORDER BY bucket DESC, update_time DESC LIMIT $5
            """,
            device_id, days, bucket_sec, before_bucket, limit)
    return [dict(r) for r in rows]


async def fall_events(db: Database, since: Optional[datetime], until: Optional[datetime], device_id: Optional[str],
                      after: Optional[Tuple[datetime, str]], limit: int) -> List[Dict[str, Any]]:
    """Events overlapping [since, until] (an unfinished event overlaps everything after its start), newest start first.
    `after` is the (started_at, device_id) of the last item of the previous page."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT device_id, started_at, ended_at, flips,
                   CASE WHEN ended_at IS NULL THEN NULL ELSE EXTRACT(EPOCH FROM ended_at - started_at)::float8 END AS duration_sec
            FROM fall_event
            WHERE ($1::timestamptz IS NULL OR ended_at IS NULL OR ended_at >= $1)
              AND ($2::timestamptz IS NULL OR started_at <= $2)
              AND ($3::text IS NULL OR device_id = $3)
              AND ($4::timestamptz IS NULL OR (started_at, device_id) < ($4::timestamptz, $5::text))
            ORDER BY started_at DESC, device_id DESC LIMIT $6
            """,
            since, until, device_id, after[0] if after else None, after[1] if after else None, limit)
    return [dict(r) for r in rows]


POI_SUMMARY_SQL = """
SELECT count(*)::int AS count,
       count(*) FILTER (WHERE s.n > 0)::int AS with_segments,
       COALESCE(sum(s.w), 0) AS planned_tonnes,
       count(*) FILTER (WHERE s.nw = 0)::int AS without_weight
FROM poi p LEFT JOIN LATERAL (
    SELECT count(*) AS n, count(weight_t) AS nw, sum(weight_t) AS w FROM poi_cable_segment WHERE poi_no = p.poi_no) s ON true
WHERE p.in_ledger
"""
POI_COLUMNS = ("p.poi_no, p.uci, p.subcon AS subcontractor, p.site_ville, p.commune_code, p.category, p.status_raw, "
               "p.occ_week_from, p.occ_week_to, p.occ_date_from, p.occ_date_to, p.received_date, p.planned_op_date, "
               "p.in_ledger, p.imported_at, s.segment_count, s.total_length_km, s.planned_tonnes")
POI_SEGMENT_AGG = ("LEFT JOIN LATERAL (SELECT count(*)::int AS segment_count, sum(length_km) AS total_length_km, "
                   "sum(weight_t) AS planned_tonnes FROM poi_cable_segment WHERE poi_no = p.poi_no) s ON true")
# filter name -> SQL fragment with one placeholder; the user's text only ever travels as the bound value
POI_FILTERS = {
    "uci": "p.uci = $%d",
    "subcontractor": "p.subcon = $%d",
    "commune": "p.commune_code = $%d",
    "category": "p.category = $%d",
    "in_ledger": "p.in_ledger = $%d",
    "network": "EXISTS (SELECT 1 FROM poi_cable_segment x WHERE x.poi_no = p.poi_no AND x.infra = $%d)",
    "cable_type": "EXISTS (SELECT 1 FROM poi_cable_segment x WHERE x.poi_no = p.poi_no AND x.cable_type = $%d)",
}


async def poi_summary(db: Database) -> Dict[str, Any]:
    async with db.pool.acquire() as conn:
        r = await conn.fetchrow(POI_SUMMARY_SQL)
    return dict(r)


async def poi_snapshot_at(db: Database) -> Optional[datetime]:
    async with db.pool.acquire() as conn:
        return await conn.fetchval("SELECT max(imported_at) FROM poi")


async def poi_page(db: Database, filters: Dict[str, Any], after: Optional[str], limit: int) -> List[Dict[str, Any]]:
    conds: List[str] = []
    args: List[Any] = []
    for name, value in filters.items():
        args.append(value)
        conds.append(POI_FILTERS[name] % len(args))  # KeyError = a filter nobody registered: a bug, not user input
    if after is not None:
        args.append(after)
        conds.append("p.poi_no > $%d" % len(args))
    args.append(limit)
    sql = "SELECT %s FROM poi p %s %s ORDER BY p.poi_no LIMIT $%d" % (
        POI_COLUMNS, POI_SEGMENT_AGG, ("WHERE " + " AND ".join(conds)) if conds else "", len(args))
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(sql, *args)
    return [dict(r) for r in rows]


async def poi_imported_at(db: Database, poi_no: str) -> Tuple[bool, Optional[datetime]]:
    """(exists, imported_at) of one work order."""
    async with db.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT imported_at FROM poi WHERE poi_no = $1", poi_no)
    return (row is not None), (row["imported_at"] if row else None)


async def poi_segments(db: Database, poi_no: str, after_seq: Optional[int], limit: int) -> List[Dict[str, Any]]:
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT seq, cable_category, cable_type, infra, length_km, weight_t, ref_min_t, ref_avg_t, ref_max_t "
            "FROM poi_cable_segment WHERE poi_no = $1 AND ($2::int IS NULL OR seq > $2) ORDER BY seq LIMIT $3",
            poi_no, after_seq, limit)
    return [dict(r) for r in rows]


async def sla_templates(db: Database, after: Optional[str], limit: int) -> List[Dict[str, Any]]:
    """Templates (sorted by name, keyset on the name) with their steps in order; at most `limit` templates."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT template, seq, step, owner, sla_text FROM sla_template_step WHERE template IN ("
            "SELECT DISTINCT template FROM sla_template_step WHERE ($1::text IS NULL OR template > $1) ORDER BY template LIMIT $2) "
            "ORDER BY template, seq", after, limit)
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not out or out[-1]["template"] != r["template"]:
            out.append({"template": r["template"], "steps": []})
        out[-1]["steps"].append({"seq": r["seq"], "step": r["step"], "owner": r["owner"], "sla_text": r["sla_text"]})
    return out


async def sla_snapshot_at(db: Database) -> Optional[datetime]:
    async with db.pool.acquire() as conn:
        return await conn.fetchval("SELECT max(imported_at) FROM sla_template_step")
