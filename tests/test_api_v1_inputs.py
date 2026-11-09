# risk: high
"""Phase 8 Task 8.3 review fixes: hostile or boundary inputs of /api/v1 must be 400 (never a 500 from the database or the datetime
range), cursors stay short however long a name is, ties and 24 h windows page and classify correctly, and a tracker that pushed before
it was registered is still a bundle. Helpers and the `db` fixture come from test_api_v1_resources (real local database, zz-test-* rows)."""
import pytest
from aiohttp.test_utils import TestClient, TestServer

from lutetia.models import Device, Telemetry
from test_api_v1_resources import AUTH, PFX, b64, db, get_json, gps, make_app, mk_manhole, mk_pois, ms_ago, walk  # noqa: F401


async def status_of(c, path):
    r = await c.get(path, headers=AUTH)
    return r.status, await r.json()


# ---- the seven classes of constructed input: each one is a 400 in the {"error": text} shape ----------------------------

NUL_CURSOR = ["a\x00b", "\x00"]
NUL_TEXT_PARAMS = ["/api/v1/pois?uci=a%00b", "/api/v1/pois?subcontractor=%00", "/api/v1/pois?network=x%00", "/api/v1/pois?cable_type=%00x",
                   "/api/v1/fall-events?device_id=a%00b"]
INT64_OUT_OF_RANGE = [2 ** 63, -2 ** 63 - 1, 10 ** 30]
INT32_OUT_OF_RANGE = [2 ** 31, -2 ** 31 - 1, 2 ** 40]
DT_OUT_OF_RANGE_CURSORS = ["0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-05:00", "0001-01-01T00:00:00+23:59"]
TIME_PARAMS_OUT_OF_RANGE = ["99999999999999999999", "-99999999999999999999", "9999-12-31T23:59:59-05:00", "0001-01-01T00:00:00%2B05:00",
                            "253402300800000", "-62135596800001"]


async def assert_400(c, path):
    status, body = await status_of(c, path)
    assert status == 400 and list(body) == ["error"] and isinstance(body["error"], str), (path, status, body)


async def test_input_class_1_nul_in_a_string_cursor(db):
    async with TestClient(TestServer(make_app(db)[0])) as c:
        for v in NUL_CURSOR:
            await assert_400(c, "/api/v1/manholes?cursor=" + b64([v]))
            await assert_400(c, "/api/v1/bundles?cursor=" + b64([v]))
            await assert_400(c, "/api/v1/pois?cursor=" + b64([v]))
            await assert_400(c, "/api/v1/fall-events?cursor=" + b64(["2026-01-01T00:00:00+00:00", v]))


async def test_input_class_2_nul_in_a_text_filter(db):
    async with TestClient(TestServer(make_app(db)[0])) as c:
        for path in NUL_TEXT_PARAMS:
            await assert_400(c, path)


async def test_input_class_3_nul_in_the_poi_no_path_segment(db):
    await mk_pois(db)
    async with TestClient(TestServer(make_app(db)[0])) as c:
        await assert_400(c, "/api/v1/pois/%sp1%%00/segments" % PFX)
        await assert_400(c, "/api/v1/pois/%00/segments")


async def test_input_class_4_track_cursor_beyond_int64(db):
    dev = PFX + "b-int64"
    await db.upsert_devices([Device("gps51", dev, dev, "GT", True, {})])
    async with TestClient(TestServer(make_app(db)[0])) as c:
        for v in INT64_OUT_OF_RANGE:
            await assert_400(c, "/api/v1/bundles/%s/track?cursor=%s" % (dev, b64([v])))
        status, _ = await status_of(c, "/api/v1/bundles/%s/track?cursor=%s" % (dev, b64([2 ** 63 - 1])))
        assert status == 200  # the largest bigint is still a value the column can hold


async def test_input_class_5_segments_cursor_beyond_int32(db):
    await mk_pois(db)
    async with TestClient(TestServer(make_app(db)[0])) as c:
        for v in INT32_OUT_OF_RANGE:
            await assert_400(c, "/api/v1/pois/%sp1/segments?cursor=%s" % (PFX, b64([v])))
        status, _ = await status_of(c, "/api/v1/pois/%sp1/segments?cursor=%s" % (PFX, b64([2 ** 31 - 1])))
        assert status == 200


async def test_input_class_6_timestamp_cursor_that_leaves_the_datetime_range_after_conversion(db):
    async with TestClient(TestServer(make_app(db)[0])) as c:
        for v in DT_OUT_OF_RANGE_CURSORS:
            await assert_400(c, "/api/v1/fall-events?cursor=" + b64([v, "d"]))
        status, _ = await status_of(c, "/api/v1/fall-events?cursor=" + b64(["0001-01-01T00:00:00+00:00", "d"]))
        assert status == 200  # the very first instant, already UTC, is representable


async def test_input_class_7_since_until_out_of_range(db):
    async with TestClient(TestServer(make_app(db)[0])) as c:
        for v in TIME_PARAMS_OUT_OF_RANGE:
            await assert_400(c, "/api/v1/fall-events?since=" + v)
            await assert_400(c, "/api/v1/fall-events?until=" + v)


# ---- L1: cursors carry ids, never names --------------------------------------------------------------------------------

async def mk_named(db, suffix, name, expected=True):
    dev = PFX + suffix
    await db.upsert_devices([Device("dingtek", dev, name, "DC414", expected, {})])
    await db.insert_telemetry([Telemetry(dev, "volt", ms_ago(5), 372.0, None, "rest")])
    return dev


async def test_manholes_with_300_character_names_page_to_the_end_with_limit_1(db):
    ids = [await mk_named(db, "long-a", "x" * 300), await mk_named(db, "long-b", "x" * 299 + "a"), await mk_named(db, "long-c", "x" * 300)]
    async with TestClient(TestServer(make_app(db)[0])) as c:
        items, pages = await walk(c, "/api/v1/manholes", limit=1)
        mine = [i["device_id"] for i in items if i["device_id"].startswith(PFX)]
        assert pages == len(items) and sorted(mine) == sorted(ids) and len(set(mine)) == 3
        # (name, device_id) order: "x"*299+"a" sorts before "x"*300; the two equal names by device_id
        assert mine == [ids[1], ids[0], ids[2]]
        first = await get_json(c, "/api/v1/manholes?limit=1")
        assert len(first["next"]) < 100  # the cursor does not grow with the name


# ---- M4 / M5: ties and the 24 h window ----------------------------------------------------------------------------------

async def test_five_same_named_manholes_and_five_same_start_events_page_one_by_one(db):
    # five manholes with one name; three more whose name order is the reverse of their id order, so an id-only comparison would skip or repeat
    same = [await mk_named(db, "tie-%d" % i, "zz-same-name") for i in range(5)]
    rev = [await mk_named(db, "rev-%d" % i, "zz-rev-%d" % (2 - i)) for i in range(3)]
    shared_ms = ms_ago(90)  # five events that start in the same millisecond, on five devices
    await db.insert_telemetry([Telemetry(d, "alarmFall", shared_ms, 1.0, None, "rest") for d in same])
    async with TestClient(TestServer(make_app(db)[0])) as c:
        items, _ = await walk(c, "/api/v1/manholes", limit=1)
        mine = [i["device_id"] for i in items if i["device_id"].startswith(PFX)]
        assert len(mine) == 8 and len(set(mine)) == 8
        by_name = {i["device_id"]: i["name"] for i in items}
        assert mine == sorted(mine, key=lambda d: (by_name[d], d))
        assert mine == [rev[2], rev[1], rev[0]] + sorted(same)  # name order first, device_id only breaks the five-way tie
        events, _ = await walk(c, "/api/v1/fall-events", limit=1)
        mine_ev = [(e["started_at"], e["device_id"]) for e in events if e["device_id"] in same]
        assert len(mine_ev) == 5 and len(set(mine_ev)) == 5 and len({s for s, _ in mine_ev}) == 1  # same start, five distinct devices
        assert mine_ev == sorted(mine_ev, reverse=True)


async def test_event_from_25_h_to_23_h_ago_is_moved_and_overlaps_a_24_h_window(db):
    dev = await mk_manhole(db, 0, last_min=60, alarms=[(25 * 60, 1), (23 * 60, 0)])
    async with TestClient(TestServer(make_app(db)[0])) as c:
        items, _ = await walk(c, "/api/v1/manholes")
        me = next(i for i in items if i["device_id"] == dev)
        assert me["status"] == "moved" and me["open_event"] is False  # it ended inside the last 24 h
        day = await get_json(c, "/api/v1/fall-events?device_id=%s&since=%d" % (dev, ms_ago(24 * 60)))
        assert len(day["items"]) == 1  # started before the window, ended inside it: overlaps
        after = await get_json(c, "/api/v1/fall-events?device_id=%s&since=%d" % (dev, ms_ago(22 * 60)))
        assert after["items"] == []  # ended before this window opened


# ---- open_event and inactive ------------------------------------------------------------------------------------------------

async def test_offline_with_open_event_stays_offline_and_inactive_beats_everything(db):
    off_open = await mk_manhole(db, 0, last_min=600, alarms=[(600, 1)])
    inactive_open = await mk_manhole(db, 1, expected=False, last_min=600, alarms=[(600, 1)])
    unknown = PFX + "mh-unknown"  # expected_online NULL
    await db.upsert_devices([Device("dingtek", unknown, unknown, "DC414", None, {})])
    async with TestClient(TestServer(make_app(db)[0])) as c:
        items, _ = await walk(c, "/api/v1/manholes")
        by = {i["device_id"]: i for i in items}
        assert (by[off_open]["status"], by[off_open]["open_event"]) == ("offline", True)
        assert (by[inactive_open]["status"], by[inactive_open]["open_event"]) == ("inactive", True)  # open_event is a fact, status is not
        assert (by[unknown]["status"], by[unknown]["open_event"]) == ("inactive", False)
        m = (await get_json(c, "/api/v1/summary"))["data"]["manholes"]
        assert m["offline_with_open_event"] == sum(1 for i in items if i["status"] == "offline" and i["open_event"]) >= 1
        assert m["inactive"] == sum(1 for i in items if i["status"] == "inactive") >= 2 and m["all"] == len(items)
        assert m["total"] + m["inactive"] == m["all"] and m["moved_24h"] + m["offline"] + m["quiet"] == m["total"]
        assert m["moving"] == sum(1 for i in items if i["status"] == "moving")


# ---- L2: bundles come from gps_position ---------------------------------------------------------------------------------------

async def test_tracker_that_pushed_before_it_was_registered_is_listed_and_has_a_track(db):
    fresh, old = PFX + "b-unreg-fresh", PFX + "b-unreg-old"
    await db.insert_gps_positions([gps(fresh, ms_ago(5)), gps(old, ms_ago(600))])  # no device row for either
    async with TestClient(TestServer(make_app(db)[0])) as c:
        listed, _ = await walk(c, "/api/v1/bundles")
        mine = {i["device_id"]: i for i in listed if i["device_id"].startswith(PFX)}
        assert set(mine) == {fresh, old}
        assert (mine[fresh]["name"], mine[fresh]["online"], mine[fresh]["lat"], mine[fresh]["moving"]) == (None, True, 22.5, True)
        assert mine[old]["online"] is False and mine[old]["at"] is not None  # silent past the 3 h limit; expected_online unknown is not "off"
        track = await get_json(c, "/api/v1/bundles/%s/track" % fresh)
        assert len(track["items"]) == 1 and track["items"][0]["lat"] == 22.5
        summary = (await get_json(c, "/api/v1/summary"))["data"]["bundles"]
        assert summary["trackers"] == len(listed) and summary["online"] == sum(1 for i in listed if i["online"])
        assert (await c.get("/api/v1/bundles/%snobody/track" % PFX, headers=AUTH)).status == 404
        await db.upsert_devices([Device("gps51", fresh, "Tracker One", "GT", True, {})])  # once registered it keeps its one place, now named
        again, _ = await walk(c, "/api/v1/bundles")
        assert [i["name"] for i in again if i["device_id"] == fresh] == ["Tracker One"]
