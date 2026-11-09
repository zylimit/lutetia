# risk: high
"""Phase 8 Task 8.3: the new /api/v1 resources (summary, manholes, fall-events, bundles, track, pois, segments, collector-status),
their envelope and cursors, scopes, and the local timing budget. Real local database, synthetic rows named zz-test-*, removed after.
Counts that other rows could disturb are asserted as deltas against a baseline read first (the local database is normally empty)."""
import base64
import dataclasses
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone

import pytest
from aiohttp import DummyCookieJar
from aiohttp.test_utils import TestClient, TestServer

import lutetia.cli
from lutetia.config import Config, load_dotenv
from lutetia.db import Database
from lutetia.models import Attribute, Device, GpsPosition, Telemetry
from lutetia.web import WebServer

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
PFX = "zz-test-v1-"
KEY = "k-" + secrets.token_hex(8)
AUTH = {"Authorization": "Bearer " + KEY}
BUDGET_SEC = 0.3
LIST_PATHS = ["/api/v1/manholes", "/api/v1/fall-events", "/api/v1/bundles", "/api/v1/pois"]


def ms_ago(minutes):
    return int((time.time() - minutes * 60) * 1000)


def gps(dev, ts_ms, moving=1):
    return GpsPosition(dev, ts_ms, ts_ms, ts_ms, 22.5, 114.0, 10000.0, 0, 0.0, 0.0, 0, 0, None, None, moving,
                       None, None, None, None, "poll", {})


def b64(obj):
    return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")


def parse_iso(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ" if "." in s else "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


@pytest.fixture
async def db():
    if not DB_URL:
        pytest.skip("DATABASE_URL not set")
    d = Database(DB_URL)
    try:
        await d.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip("database unreachable: %s" % e)
    await d.migrate(lutetia.cli.SQL_DIR)
    await wipe(d)
    yield d
    await wipe(d)
    await d.close()


async def wipe(d):
    like = PFX + "%"
    async with d.pool.acquire() as conn:
        for sql in ("DELETE FROM sensor_telemetry WHERE device_id LIKE $1", "DELETE FROM sensor_attribute WHERE device_id LIKE $1",
                    "DELETE FROM gps_position WHERE device_id LIKE $1", "DELETE FROM device WHERE device_id LIKE $1",
                    "DELETE FROM poi WHERE poi_no LIKE $1"):  # segments go with their poi (ON DELETE CASCADE)
            await conn.execute(sql, like)


def make_app(db, tmp_path=None, entries=None):
    base = dict(api_key=KEY, dashboard_pwd="p-" + secrets.token_hex(4), orange_pwd="o-" + secrets.token_hex(4),
                huawei_pwd="h-" + secrets.token_hex(4), dashboard_host="127.0.0.1", login_lockout=False,
                session_secret="s-" + secrets.token_hex(8), callers_file="", legacy_rate_per_min=100000, session_rate_per_min=100000)
    if entries is not None:
        f = tmp_path / "callers.json"
        f.write_text(json.dumps(entries), encoding="utf-8")
        base["callers_file"] = str(f)
    cfg = dataclasses.replace(Config.from_env(), **base)
    return WebServer(cfg, db, datetime.now(timezone.utc)).build_app(), cfg


async def get_json(c, path, headers=AUTH, status=200):
    r = await c.get(path, headers=headers)
    assert r.status == status, (path, r.status, await r.text())
    return await r.json()


async def login(c, cfg, user):
    pwd = {"admin": cfg.dashboard_pwd, "orange": cfg.orange_pwd, "huawei": cfg.huawei_pwd}[user]
    r = await c.post("/login", data={"username": user, "password": pwd, "next": ""}, allow_redirects=False)
    return {"Cookie": "lutetia_session=" + r.cookies["lutetia_session"].value}


async def walk(c, path, params="", headers=AUTH, limit=None):
    """Follow `next` to the end; (all items, number of pages)."""
    items, pages, cursor = [], 0, None
    while True:
        qs = [params] if params else []
        if limit:
            qs.append("limit=%d" % limit)
        if cursor:
            qs.append("cursor=" + cursor)
        body = await get_json(c, path + ("?" + "&".join(qs) if qs else ""), headers)
        items += body["items"]
        pages += 1
        assert pages < 50
        cursor = body["next"]
        if cursor is None:
            return items, pages


# ---- data builders ----------------------------------------------------------------------------------------------

async def mk_manhole(db, i, *, expected=True, last_min=5, interval=None, alarms=(), coords=None):
    dev = "%smh-%02d" % (PFX, i)
    await db.upsert_devices([Device("dingtek", dev, dev, "DC414", expected, {})])
    rows = [Telemetry(dev, "volt", ms_ago(last_min), 372.0, None, "rest"), Telemetry(dev, "rsrp", ms_ago(last_min), -950.0, None, "rest")]
    rows += [Telemetry(dev, "alarmFall", ms_ago(m), float(v), None, "rest") for m, v in alarms]
    await db.insert_telemetry(rows)
    attrs = []
    if interval:
        attrs.append(Attribute(dev, "uploadInterval", "%dh" % interval, None))
    if coords:
        attrs += [Attribute(dev, "latitude", coords[0], None), Attribute(dev, "longitude", coords[1], None)]
    await db.upsert_attributes(attrs)
    return dev


async def twelve_manholes(db):
    """2 offline (one of them with an unfinished event), 1 moving, 2 moved within 24 h, 6 quiet (one event ended > 24 h ago,
    one silent 5 h but uploading every 4 h), 1 inactive (not expected online, silent 100 h: never offline, never quiet)."""
    ids = {}
    ids["offline_with_open_event"] = await mk_manhole(db, 0, last_min=600, alarms=[(600, 1)])
    ids["offline"] = await mk_manhole(db, 1, last_min=600)
    ids["moving"] = await mk_manhole(db, 2, alarms=[(20, 1)])
    ids["moved_5h"] = await mk_manhole(db, 3, last_min=60, alarms=[(300, 1), (290, 0)])
    ids["moved_23h"] = await mk_manhole(db, 4, last_min=60, alarms=[(23 * 60 + 30, 1), (23 * 60, 0)])
    ids["quiet_old_event"] = await mk_manhole(db, 5, last_min=60, alarms=[(26 * 60, 1), (25 * 60, 0)])
    ids["inactive"] = await mk_manhole(db, 6, expected=False, last_min=6000)
    ids["quiet_slow_uploader"] = await mk_manhole(db, 7, last_min=300, interval=4)
    for i in (8, 9, 10, 11):
        ids["quiet_%d" % i] = await mk_manhole(db, i, coords=("48.85660", "2.35220") if i == 8 else None)
    return ids


async def mk_bundles(db):
    out = {}
    for name, expected, pos_min in (("online", True, 5), ("stale", True, 600), ("never", True, None), ("not_expected", False, 5)):
        dev = PFX + "b-" + name
        await db.upsert_devices([Device("gps51", dev, dev, "GT", expected, {})])
        if pos_min is not None:
            await db.insert_gps_positions([gps(dev, ms_ago(pos_min))])
        out[name] = dev
    return out


async def mk_pois(db):
    """p1 two weighted segments; p2 a segment without weight; p3 no segments; p4 gone from the ledger; p5 one weighted segment."""
    spec = [("p1", "A", "S1", "C1", "Transport", True, "2026-03-01T10:00:00Z",
             [(1, "T1", "sousterrain", 1.5, 2.0), (2, "T2", "aerien", 0.5, 3.0)]),
            ("p2", "A", "S2", "C2", "Distribution", True, "2026-03-02T10:00:00Z", [(1, "T2", "sousterrain", 1.0, None)]),
            ("p3", "B", "S1", "C1", "Transport", True, "2026-03-03T10:00:00Z", []),
            ("p4", "B", "S2", "C2", "Distribution", False, "2026-03-04T10:00:00Z", [(1, "T3", "sousterrain", 9.0, 10.0)]),
            ("p5", "B", "S1", "C1", "Transport", True, "2099-01-01T00:00:00Z", [(1, "T1", "sousterrain", 2.0, 4.0)])]
    async with db.pool.acquire() as conn:
        for n, uci, sub, com, cat, led, at, segs in spec:
            no = PFX + n
            await conn.execute(
                "INSERT INTO poi (poi_no, uci, subcon, commune_code, category, in_ledger, content_sha, raw_sha, imported_at, "
                "planned_op_date) VALUES ($1, $2, $3, $4, $5, $6, 'c', 'r', $7::timestamptz, '2026-04-01')",
                no, PFX + "uci-" + uci, PFX + "sub-" + sub, PFX + "com-" + com, cat, led, datetime.fromisoformat(at.replace("Z", "+00:00")))
            for seq, ctype, infra, km, t in segs:
                await conn.execute("INSERT INTO poi_cable_segment (poi_no, seq, cable_category, cable_type, infra, length_km, weight_t) "
                                   "VALUES ($1, $2, 'DECS2', $3, $4, $5, $6)", no, seq, PFX + "type-" + ctype, infra, km, t)


async def fall_events_of(db, dev, n, spacing_min=120):
    """n separate events (non-zero then zero five minutes later; `spacing_min` apart so they never merge), the newest finished."""
    rows = []
    for k in range(n):
        base = (n - k) * spacing_min + 10
        rows += [Telemetry(dev, "alarmFall", ms_ago(base), 1.0, None, "rest"), Telemetry(dev, "alarmFall", ms_ago(base - 5), 0.0, None, "rest")]
    await db.insert_telemetry(rows)


# ---- summary --------------------------------------------------------------------------------------------------

async def test_summary_twelve_manholes_example_and_three_bands_add_up(db):
    async with TestClient(TestServer(make_app(db)[0])) as c:
        base = (await get_json(c, "/api/v1/summary"))["data"]["manholes"]
        await twelve_manholes(db)
        body = await get_json(c, "/api/v1/summary")
        m = body["data"]["manholes"]
        assert {k: m[k] - base[k] for k in m} == {"total": 11, "inactive": 1, "all": 12, "moved_24h": 3, "moving": 1, "offline": 2,
                                                   "offline_with_open_event": 1, "quiet": 6}
        assert m["moved_24h"] + m["offline"] + m["quiet"] == m["total"] and m["total"] + m["inactive"] == m["all"]
        assert set(body) == {"data", "as_of"} and body["as_of"].endswith("Z")
        assert set(body["data"]) == {"manholes", "bundles", "pois", "collector"}


async def test_summary_bundles_pois_and_collector_blocks(db):
    async with TestClient(TestServer(make_app(db)[0])) as c:
        base = (await get_json(c, "/api/v1/summary"))["data"]
        await mk_bundles(db)
        await mk_pois(db)
        try:
            async with db.pool.acquire() as conn:
                await conn.execute("DELETE FROM collector_status")
            stale = (await get_json(c, "/api/v1/summary"))["data"]
            assert stale["collector"] == {"updated_at": None, "stale": True}  # no heartbeat row is stale, never fresh
            await db.write_heartbeat("t", None, True, True, {})
            data = (await get_json(c, "/api/v1/summary"))["data"]
            assert data["bundles"]["trackers"] - base["bundles"]["trackers"] == 4
            assert data["bundles"]["online"] - base["bundles"]["online"] == 1  # stale, never-positioned and not-expected are not online
            assert data["bundles"]["last_position_at"] is not None
            p, p0 = data["pois"], base["pois"]
            assert p["count"] - p0["count"] == 4 and p["with_segments"] - p0["with_segments"] == 3  # p4 is gone from the ledger
            listed, _ = await walk(c, "/api/v1/pois")  # SC-10: the number on the overview opens into a list that has exactly that many
            assert p["count"] == len(listed) and p["with_segments"] == sum(1 for i in listed if i["segment_count"] > 0)
            assert p["without_weight"] - p0["without_weight"] == 2  # p2 has a segment but no weight, p3 has no segment
            assert p["planned_tonnes"] - p0["planned_tonnes"] == pytest.approx(9.0)  # 2 + 3 + 4; p4's 10 t and p2's missing weight stay out
            assert set(data["collector"]) == {"updated_at", "stale"} and data["collector"]["stale"] is False
        finally:
            async with db.pool.acquire() as conn:
                await conn.execute("DELETE FROM collector_status")


# ---- manholes ---------------------------------------------------------------------------------------------------

async def test_manholes_status_priority_fields_and_paging_to_the_end(db):
    ids = await twelve_manholes(db)
    async with TestClient(TestServer(make_app(db)[0])) as c:
        items, pages = await walk(c, "/api/v1/manholes", limit=5)
        mine = [i for i in items if i["device_id"].startswith(PFX)]
        assert len(mine) == 12 and pages >= 3
        assert [i["device_id"] for i in mine] == sorted(i["device_id"] for i in mine)
        by = {i["device_id"]: i for i in mine}
        expect = {"offline_with_open_event": "offline", "offline": "offline", "moving": "moving", "moved_5h": "moved",
                  "moved_23h": "moved", "quiet_old_event": "quiet", "inactive": "inactive", "quiet_slow_uploader": "quiet"}
        for k, status in expect.items():
            assert by[ids[k]]["status"] == status, k
        assert {i["status"] for i in items} <= {"inactive", "offline", "moving", "moved", "quiet"}
        # open_event is every device's own fact, independent of status: an offline device with an unfinished event keeps status offline
        assert {k: by[ids[k]]["open_event"] for k in expect} == {"offline_with_open_event": True, "offline": False, "moving": True,
                                                                  "moved_5h": False, "moved_23h": False, "quiet_old_event": False,
                                                                  "inactive": False, "quiet_slow_uploader": False}
        one = by[ids["quiet_8"]]
        assert set(one) == {"device_id", "name", "status", "open_event", "volt", "rsrp", "last_seen", "lat", "lon", "location_verified"}
        assert one["volt"] == pytest.approx(3.72) and one["rsrp"] == pytest.approx(-95.0)  # converted values (sensor_telemetry_v)
        assert (one["lat"], one["lon"]) == (48.8566, 2.3522) and one["location_verified"] is False
        assert by[ids["quiet_9"]]["lat"] is None and by[ids["quiet_9"]]["lon"] is None
        assert abs(parse_iso(one["last_seen"]).timestamp() - (time.time() - 300)) < 60
        full = await get_json(c, "/api/v1/manholes")
        assert set(full) == {"items", "as_of", "next"} and full["next"] is None and len(full["items"]) == len(items)
        last = await get_json(c, "/api/v1/manholes?limit=%d" % (len(items) - 1))
        past = await get_json(c, "/api/v1/manholes?cursor=" + b64([last["items"][-1]["device_id"]]))
        assert past["items"][0]["device_id"] == items[-1]["device_id"] and past["next"] is None
        end = await get_json(c, "/api/v1/manholes?cursor=" + b64([items[-1]["device_id"]]))
        assert end["items"] == [] and end["next"] is None  # an empty page keeps the envelope
        assert (await c.get("/api/v1/manholes?cursor=" + b64([PFX + "gone"]), headers=AUTH)).status == 400  # an id nobody lists is a bad cursor


# ---- fall events ----------------------------------------------------------------------------------------------------

async def test_fall_events_fields_order_filters_and_paging(db):
    dev = await mk_manhole(db, 0, alarms=[(15, 1)])
    other = await mk_manhole(db, 1)
    await fall_events_of(db, other, 5)
    async with TestClient(TestServer(make_app(db)[0])) as c:
        everything, pages = await walk(c, "/api/v1/fall-events", limit=2)
        mine = [e for e in everything if e["device_id"].startswith(PFX)]
        assert len(mine) == 6 and pages >= 3
        keys = [(e["started_at"], e["device_id"]) for e in mine]
        assert keys == sorted(keys, reverse=True)
        open_ev = [e for e in mine if e["device_id"] == dev]
        assert len(open_ev) == 1 and open_ev[0]["ended_at"] is None and open_ev[0]["duration_sec"] is None and open_ev[0]["flips"] == 1
        done = [e for e in mine if e["device_id"] == other]
        assert len(done) == 5 and all(e["duration_sec"] == pytest.approx(300.0) and e["ended_at"] for e in done)
        assert set(done[0]) == {"device_id", "started_at", "ended_at", "flips", "duration_sec"}
        only, p = await walk(c, "/api/v1/fall-events", "device_id=" + other, limit=2)
        assert len(only) == 5 and p == 3
        none = await get_json(c, "/api/v1/fall-events?device_id=" + PFX + "nobody")
        assert none["items"] == [] and none["next"] is None and none["as_of"]
        since = await get_json(c, "/api/v1/fall-events?device_id=%s&since=%d" % (other, ms_ago(300)))
        assert len(since["items"]) == 2  # events that began 250 and 130 minutes ago; the three older ones ended before the cutoff
        until = await get_json(c, "/api/v1/fall-events?device_id=%s&until=%d" % (other, ms_ago(300)))
        assert len(until["items"]) == 3  # began 610, 490 and 370 minutes ago
        day = await get_json(c, "/api/v1/fall-events?since=%d" % ms_ago(24 * 60))
        assert dev in [e["device_id"] for e in day["items"]]  # an unfinished event overlaps any window that ends after its start


async def test_session_and_key_see_the_same_fall_event_count_sc14(db):
    await mk_manhole(db, 0, alarms=[(15, 1)])
    await fall_events_of(db, await mk_manhole(db, 1), 4)
    app, cfg = make_app(db)
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        session = await login(c, cfg, "orange")
        via_key, _ = await walk(c, "/api/v1/fall-events", limit=2)
        via_session, _ = await walk(c, "/api/v1/fall-events", headers=session, limit=3)
        assert len(via_key) == len(via_session) >= 5 and via_key == via_session


# ---- bundles and track ------------------------------------------------------------------------------------------------

async def test_bundles_fields_online_and_paging(db):
    ids = await mk_bundles(db)
    async with TestClient(TestServer(make_app(db)[0])) as c:
        items, pages = await walk(c, "/api/v1/bundles", limit=3)
        mine = {i["device_id"]: i for i in items if i["device_id"].startswith(PFX)}
        assert len(mine) == 4 and pages >= 2
        on = mine[ids["online"]]
        assert set(on) == {"device_id", "name", "lat", "lon", "at", "moving", "online"}
        assert (on["lat"], on["lon"], on["moving"]) == (22.5, 114.0, True)
        assert [mine[ids[k]]["online"] for k in ("online", "stale", "never", "not_expected")] == [True, False, False, False]
        never = mine[ids["never"]]
        assert (never["lat"], never["lon"], never["at"], never["moving"]) == (None, None, None, None)
        past = await get_json(c, "/api/v1/bundles?cursor=" + b64(["~"]))
        assert past["items"] == [] and past["next"] is None


async def test_track_thinned_newest_first_pages_to_the_end_and_days_bounds(db):
    dev = PFX + "b-track"
    await db.upsert_devices([Device("gps51", dev, dev, "GT", True, {})])
    stamps = [ms_ago(m) for m in range(1, 6 * 24 * 60, 4)]  # one point every 4 minutes for six days
    await db.insert_gps_positions([gps(dev, s) for s in stamps])
    buckets = {s // 300000 for s in stamps}
    async with TestClient(TestServer(make_app(db)[0])) as c:
        items, pages = await walk(c, "/api/v1/bundles/%s/track" % dev, "days=7", limit=1000)
        assert len(items) == len(buckets) and pages == 2
        assert set(items[0]) == {"at", "lat", "lon", "speed_kmh", "moving"}
        ats = [i["at"] for i in items]
        assert ats == sorted(ats, reverse=True) and len(set(ats)) == len(ats)
        day, _ = await walk(c, "/api/v1/bundles/%s/track" % dev, "days=1", limit=1000)
        assert 250 <= len(day) <= 290
        default = await get_json(c, "/api/v1/bundles/%s/track" % dev)  # days defaults to 7, limit to 100
        assert len(default["items"]) == 100 and default["next"]
        empty_dev = PFX + "b-empty"
        await db.upsert_devices([Device("gps51", empty_dev, empty_dev, "GT", True, {})])
        empty = await get_json(c, "/api/v1/bundles/%s/track" % empty_dev)
        assert empty["items"] == [] and empty["next"] is None and empty["as_of"]


# ---- pois and segments -----------------------------------------------------------------------------------------------

async def test_pois_fields_snapshot_marks_filters_and_paging(db):
    await mk_pois(db)
    async with TestClient(TestServer(make_app(db)[0])) as c:
        items, pages = await walk(c, "/api/v1/pois", limit=2)
        mine = {i["poi_no"]: i for i in items if i["poi_no"].startswith(PFX)}
        assert sorted(mine) == [PFX + n for n in ("p1", "p2", "p3", "p5")] and pages >= 2  # p4 is gone from the ledger: not listed by default
        first = await get_json(c, "/api/v1/pois?limit=1000")
        assert first["source"] == "excel-snapshot" and first["as_of"] == "2099-01-01T00:00:00Z" and first["next"] is None
        p1, p2, p3 = (mine[PFX + n] for n in ("p1", "p2", "p3"))
        assert (p1["segment_count"], p1["planned_tonnes"], p1["total_length_km"]) == (2, 5.0, 2.0)
        assert p1["subcontractor"] == PFX + "sub-S1" and p1["commune_code"] == PFX + "com-C1" and p1["planned_op_date"] == "2026-04-01"
        assert p2["segment_count"] == 1 and p2["planned_tonnes"] is None  # weight pending is null, never 0
        assert (p3["segment_count"], p3["planned_tonnes"], p3["total_length_km"]) == (0, None, None)
        assert p1["in_ledger"] is True and "raw" not in p1
        removed, _ = await walk(c, "/api/v1/pois", "include_removed=true", limit=2)
        assert {i["poi_no"][len(PFX):]: i["in_ledger"] for i in removed if i["poi_no"].startswith(PFX)} == {
            "p1": True, "p2": True, "p3": True, "p4": False, "p5": True}

        async def nos(params):
            body = await get_json(c, "/api/v1/pois?" + params)
            assert body["source"] == "excel-snapshot"
            return sorted(i["poi_no"][len(PFX):] for i in body["items"])

        assert await nos("uci=" + PFX + "uci-A") == ["p1", "p2"]
        assert await nos("subcontractor=" + PFX + "sub-S1") == ["p1", "p3", "p5"]
        assert await nos("commune=" + PFX + "com-C2") == ["p2"]
        assert await nos("category=Distribution&uci=" + PFX + "uci-B") == []  # p4 is the only one, and it is gone from the ledger
        assert await nos("cable_type=" + PFX + "type-T1") == ["p1", "p5"]
        assert await nos("network=aerien&uci=" + PFX + "uci-A") == ["p1"]  # network = segment infra
        assert await nos("uci=" + PFX + "uci-B") == ["p3", "p5"]
        assert await nos("include_removed=true&uci=" + PFX + "uci-B") == ["p3", "p4", "p5"]
        assert await nos("include_removed=true&category=Distribution&uci=" + PFX + "uci-B") == ["p4"]
        assert await nos("uci=" + PFX + "uci-A&subcontractor=" + PFX + "sub-S2&cable_type=" + PFX + "type-T2") == ["p2"]
        empty = await get_json(c, "/api/v1/pois?uci=" + PFX + "nobody")
        assert empty["items"] == [] and empty["next"] is None and empty["source"] == "excel-snapshot" and empty["as_of"]
        hostile = await get_json(c, "/api/v1/pois?uci=x'%20OR%20'1'='1")  # a quote is only a value that matches nothing
        assert hostile["items"] == []


async def test_pois_snapshot_as_of_is_null_when_nothing_was_imported(db):
    async with db.pool.acquire() as conn:
        if await conn.fetchval("SELECT count(*) FROM poi"):
            pytest.skip("poi table holds non-test rows")  # visible in -rs; the local database is normally empty
    async with TestClient(TestServer(make_app(db)[0])) as c:
        assert await get_json(c, "/api/v1/pois") == {"items": [], "as_of": None, "next": None, "source": "excel-snapshot"}


async def test_segments_fields_order_paging_empty_and_unknown(db):
    await mk_pois(db)
    async with TestClient(TestServer(make_app(db)[0])) as c:
        items, pages = await walk(c, "/api/v1/pois/%sp1/segments" % PFX, limit=1)
        assert pages == 2 and [i["seq"] for i in items] == [1, 2]
        assert set(items[0]) == {"seq", "cable_category", "cable_type", "infra", "length_km", "weight_t", "ref_min_t", "ref_avg_t", "ref_max_t"}
        assert (items[0]["length_km"], items[0]["weight_t"], items[0]["ref_avg_t"], items[0]["infra"]) == (1.5, 2.0, None, "sousterrain")
        body = await get_json(c, "/api/v1/pois/%sp1/segments" % PFX)
        assert body["source"] == "excel-snapshot" and body["as_of"] == "2026-03-01T10:00:00Z" and body["next"] is None
        none = await get_json(c, "/api/v1/pois/%sp3/segments" % PFX)
        assert none["items"] == [] and none["next"] is None
        assert await get_json(c, "/api/v1/pois/%snope/segments" % PFX, status=404) == {"error": "unknown poi"}


# ---- collector status -------------------------------------------------------------------------------------------------

async def test_collector_status_matches_the_ops_overview_view_and_empty_case(db):
    app, cfg = make_app(db)
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        admin = await login(c, cfg, "admin")
        try:
            async with db.pool.acquire() as conn:
                await conn.execute("DELETE FROM collector_status")
            empty = await get_json(c, "/api/v1/collector-status")
            assert empty["data"]["collector"]["stale"] is True and empty["data"]["collector"]["updated_at"] is None
            assert empty["data"]["receiver"] is None
            await db.write_heartbeat("v-test", None, True, True, {"received": 7, "collector_started_at": "2026-11-09T00:00:00Z"})
            body = await get_json(c, "/api/v1/collector-status")
            assert set(body) == {"data", "as_of"} and set(body["data"]) == {"collector", "receiver"}
            ops = await get_json(c, "/dashboard/data/overview", headers=admin)
            for k in ("version", "ws_connected", "polling", "stale", "collector_started_at", "push_count_24h", "updated_at"):
                assert body["data"]["collector"][k] == ops["collector"][k], k
            assert set(body["data"]["collector"]) == set(ops["collector"]) and set(body["data"]["receiver"]) == set(ops["receiver"])
            assert body["data"]["collector"]["age_sec"] < 30 and body["data"]["receiver"]["received"] == 7
            async with db.pool.acquire() as conn:
                await conn.execute("UPDATE collector_status SET updated_at = now() - interval '91 seconds' WHERE id = 1")
            assert (await get_json(c, "/api/v1/collector-status"))["data"]["collector"]["stale"] is True
        finally:
            async with db.pool.acquire() as conn:
                await conn.execute("DELETE FROM collector_status")


# ---- bad parameters, unknown ids -------------------------------------------------------------------------------------

BAD_LIMIT_CURSOR = ["limit=0", "limit=1001", "limit=-1", "limit=abc", "limit=", "limit=1.5", "cursor=!!!", "cursor=" + "A" * 600,
                    "cursor=" + b64({"a": 1}), "cursor=" + b64([1, 2, 3, 4]), "cursor=" + b64("x"), "cursor=e30"]


@pytest.mark.parametrize("kind", ["manholes", "fall-events", "bundles", "pois", "track", "segments"])
@pytest.mark.parametrize("bad", BAD_LIMIT_CURSOR)
async def test_bad_limit_or_cursor_is_400_in_the_error_shape(db, kind, bad):
    dev = PFX + "b-x"
    await db.upsert_devices([Device("gps51", dev, dev, "GT", True, {})])
    async with db.pool.acquire() as conn:
        await conn.execute("INSERT INTO poi (poi_no, content_sha, raw_sha) VALUES ($1, 'c', 'r')", PFX + "x")
    path = {"track": "/api/v1/bundles/%s/track" % dev, "segments": "/api/v1/pois/%sx/segments" % PFX}.get(kind, "/api/v1/" + kind)
    async with TestClient(TestServer(make_app(db)[0])) as c:
        r = await c.get(path + "?" + bad, headers=AUTH)
        body = await r.json()
        assert r.status == 400 and list(body) == ["error"] and isinstance(body["error"], str), (path, bad, r.status)


async def test_each_resource_rejects_its_own_bad_parameters_and_unknown_ids(db):
    dev = PFX + "b-known"
    await db.upsert_devices([Device("gps51", dev, dev, "GT", True, {}), Device("dingtek", PFX + "mh-dingtek", "n", "DC414", True, {})])
    async with TestClient(TestServer(make_app(db)[0])) as c:
        for qs in ("days=0", "days=31", "days=-1", "days=abc", "days=", "days=7.5"):
            assert (await c.get("/api/v1/bundles/%s/track?%s" % (dev, qs), headers=AUTH)).status == 400, qs
        assert (await c.get("/api/v1/bundles/%s/track?days=30" % dev, headers=AUTH)).status == 200
        assert (await c.get("/api/v1/bundles/%s/track?days=1" % dev, headers=AUTH)).status == 200
        assert (await c.get("/api/v1/bundles/%snobody/track" % PFX, headers=AUTH)).status == 404
        assert (await c.get("/api/v1/bundles/%smh-dingtek/track" % PFX, headers=AUTH)).status == 404  # a manhole is not a bundle
        assert (await c.get("/api/v1/bundles/bad%20id/track", headers=AUTH)).status == 400
        assert (await c.get("/api/v1/bundles/%snobody/track?days=99" % PFX, headers=AUTH)).status == 400  # parameters before lookup
        for qs in ("since=yesterday", "until=1e3", "device_id=bad%20id", "since=2026-02-01T00:00:00Z&until=2026-01-01T00:00:00Z"):
            assert (await c.get("/api/v1/fall-events?" + qs, headers=AUTH)).status == 400, qs
        assert (await c.get("/api/v1/fall-events?since=2026-01-01T00:00:00%2B01:00", headers=AUTH)).status == 200
        for qs in ("include_removed=false", "include_removed=maybe", "include_removed=1", "include_removed=TRUE", "uci=" + "x" * 129):
            assert (await c.get("/api/v1/pois?" + qs, headers=AUTH)).status == 400, qs
        assert await get_json(c, "/api/v1/pois/nobody/segments", status=404) == {"error": "unknown poi"}


# ---- scopes ------------------------------------------------------------------------------------------------------------

def _entry(name, key, scopes):
    return {"name": name, "key_sha256": hashlib.sha256(key.encode()).hexdigest(), "scopes": scopes, "origins": [], "rate_per_min": 100000}


async def test_scopes_401_403_and_summary_pois_null_without_poi_scope(db, tmp_path):
    bundles = await mk_bundles(db)
    await mk_pois(db)
    keys = {n: secrets.token_hex(12) for n in ("iot", "poi", "status", "iotpoi")}
    scopes = {"iot": ["iot:read"], "poi": ["poi:read"], "status": ["status:read"], "iotpoi": ["iot:read", "poi:read"]}
    app, cfg = make_app(db, tmp_path, [_entry(n, keys[n], scopes[n]) for n in keys])
    paths = {"iot:read": ["/api/v1/summary", "/api/v1/manholes", "/api/v1/fall-events", "/api/v1/bundles",
                          "/api/v1/bundles/%s/track" % bundles["online"]],
             "poi:read": ["/api/v1/pois", "/api/v1/pois/%sp1/segments" % PFX], "status:read": ["/api/v1/collector-status"]}
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        for scope, plist in paths.items():
            for p in plist:
                assert (await c.get(p)).status == 401, p
                assert (await c.get(p, headers={"Authorization": "Bearer nope"})).status == 401, p
                for name in keys:
                    r = await c.get(p, headers={"Authorization": "Bearer " + keys[name]})
                    if scope in scopes[name]:
                        assert r.status == 200, (name, p)
                    else:
                        assert r.status == 403 and await r.json() == {"error": "forbidden"}, (name, p)  # no data in the body
        summary_iot = (await get_json(c, "/api/v1/summary", {"Authorization": "Bearer " + keys["iot"]}))["data"]
        assert summary_iot["pois"] is None and summary_iot["manholes"] is not None
        summary_both = (await get_json(c, "/api/v1/summary", {"Authorization": "Bearer " + keys["iotpoi"]}))["data"]
        assert summary_both["pois"]["count"] >= 4
        # sessions: every account reads iot and poi; only admin reads collector-status
        for user, ops in (("admin", 200), ("orange", 403), ("huawei", 403)):
            ck = await login(c, cfg, user)
            for p in paths["iot:read"] + paths["poi:read"]:
                assert (await c.get(p, headers=ck)).status == 200, (user, p)
            assert (await c.get("/api/v1/collector-status", headers=ck)).status == ops, user
            assert (await get_json(c, "/api/v1/summary", ck))["data"]["pois"] is not None


async def test_all_v1_routes_are_get_only(db):
    app, _ = make_app(db)
    seen = set()
    for route in app.router.routes():
        path = getattr(getattr(route, "resource", None), "canonical", "") or ""
        if path.startswith("/api/v1/"):
            seen.add(path)
            assert route.method in ("GET", "HEAD"), (path, route.method)
    assert {"/api/v1/summary", "/api/v1/manholes", "/api/v1/fall-events", "/api/v1/bundles", "/api/v1/bundles/{device_id}/track",
            "/api/v1/pois", "/api/v1/pois/{poi_no}/segments", "/api/v1/collector-status", "/api/v1/devices", "/api/v1/positions",
            "/api/v1/telemetry", "/api/v1/status"} <= seen


# ---- timing -------------------------------------------------------------------------------------------------------------

async def test_every_list_resource_answers_within_the_local_budget(db):
    await twelve_manholes(db)
    await mk_bundles(db)
    await mk_pois(db)
    # production-sized alarmFall history (17,590 rows over 12 devices on 2026-11-08): 12 x 1,500 flips, 25 minutes apart, ~26 days
    await db.insert_telemetry([Telemetry("%smh-%02d" % (PFX, i), "alarmFall", ms_ago(40 + 25 * k), float(k % 2), None, "rest")
                               for i in range(12) for k in range(1500)])
    dev = PFX + "b-track"
    await db.upsert_devices([Device("gps51", dev, dev, "GT", True, {})])
    await db.insert_gps_positions([gps(dev, ms_ago(m)) for m in range(1, 6 * 24 * 60, 4)])
    paths = LIST_PATHS + ["/api/v1/summary", "/api/v1/collector-status", "/api/v1/bundles/%s/track?days=7&limit=1000" % dev,
                          "/api/v1/pois/%sp1/segments" % PFX, "/api/v1/fall-events?since=%d" % ms_ago(7 * 24 * 60)]
    async with TestClient(TestServer(make_app(db)[0])) as c:
        await get_json(c, "/api/v1/manholes")  # warm the pool once
        for p in paths:
            t0 = time.perf_counter()
            r = await c.get(p, headers=AUTH)
            await r.read()
            took = time.perf_counter() - t0
            print("timing %-52s %.3f s" % (p.split("?")[0].replace(PFX, ""), took))
            assert r.status == 200 and took < BUDGET_SEC, (p, took)
