# risk: high
"""Task 9.3: GET /api/v1/manholes/{device_id}/series (voltage and signal for the project dashboard's manhole drawer).
- days=7: raw readings, oldest first; days=30: hourly averages (avg of the readings in each hour)
- a manhole without readings answers two empty series; days outside {7, 30} is 400; an unknown or non-manhole id is 404
- iot:read only: a poi:read-only key is 403 with no data in the body; GET only
Real local database, synthetic rows named zz-test-v1-series-*, removed after; no real device id, coordinate or credential."""
import secrets
import time

import pytest
from aiohttp import DummyCookieJar
from aiohttp.test_utils import TestClient, TestServer

from lutetia.models import Device, Telemetry
import test_api_v1_resources as base
from test_api_v1_resources import AUTH, PFX, _entry, get_json, login, make_app, parse_iso

db = base.db  # the shared database fixture (synthetic zz-test-v1-* rows, wiped before and after)
DEV = PFX + "series-mh"
URL = "/api/v1/manholes/%s/series"


def hour_ago_ms(hours, minute):
    """A reading `hours` whole hours back, at `minute` past that hour (UTC): rows of one hour share one bucket."""
    top = int(time.time() // 3600 * 3600)
    return (top - hours * 3600 + minute * 60) * 1000


async def mk_series(db):
    await db.upsert_devices([Device("dingtek", DEV, "series", "DC414", True, {}), Device("dingtek", PFX + "series-empty", None, "DC414", True, {}),
                             Device("gps51", PFX + "series-gps", "g", "GT", True, {})])
    rows = []
    for h in (3, 50, 400):  # 3 h and 50 h are inside 7 days; 400 h (16.7 d) only inside 30 days
        rows += [Telemetry(DEV, "volt", hour_ago_ms(h, 5), 360.0, None, "rest"), Telemetry(DEV, "volt", hour_ago_ms(h, 35), 370.0, None, "rest"),
                 Telemetry(DEV, "rsrp", hour_ago_ms(h, 5), -900.0, None, "rest")]
    rows.append(Telemetry(DEV, "alarmFall", hour_ago_ms(3, 6), 1.0, None, "rest"))  # another key: never in the series
    rows.append(Telemetry(DEV, "volt", hour_ago_ms(24 * 40, 0), 380.0, None, "rest"))  # 40 days back: in neither
    await db.insert_telemetry(rows)


async def test_seven_days_raw_and_thirty_days_hourly(db):
    await mk_series(db)
    app, _ = make_app(db)
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        week = await get_json(c, URL % DEV + "?days=7")
        d = week["data"]
        assert d["device_id"] == DEV and d["days"] == 7 and d["hourly"] is False and d["truncated"] is False
        assert len(d["volt"]) == 4 and len(d["rsrp"]) == 2  # two volt readings in each of two hours, raw
        ats = [parse_iso(p["at"]) for p in d["volt"]]
        assert ats == sorted(ats)  # oldest first
        si = {p["value"] for p in d["volt"]}
        assert len(si) == 2 and all(isinstance(v, float) for v in si)
        assert set(week) == {"data", "as_of"} and week["as_of"].endswith("Z")
        assert (await get_json(c, URL % DEV))["data"]["days"] == 7  # default

        month = (await get_json(c, URL % DEV + "?days=30"))["data"]
        assert month["days"] == 30 and month["hourly"] is True
        assert len(month["volt"]) == 3 and len(month["rsrp"]) == 3  # one point per hour bucket, 40-day reading excluded
        for p in month["volt"]:
            at = parse_iso(p["at"])
            assert at.minute == 0 and at.second == 0  # stamped at the start of the hour
        raw = sorted(p["value"] for p in d["volt"])
        assert month["volt"][-1]["value"] == pytest.approx((raw[0] + raw[-1]) / 2)  # avg of the two readings in that hour


async def test_week_of_two_minute_readings_is_cut_to_the_newest_and_flagged(db):
    """5040 raw readings in 7 days (one every 2 min) exceed SERIES_MAX_POINTS: truncated is true and what stays is the NEWEST."""
    from lutetia.web.data import SERIES_MAX_POINTS
    await db.upsert_devices([Device("dingtek", DEV, "series", "DC414", True, {})])
    newest = int(time.time() * 1000) - 60_000  # one minute ago
    stamps = [newest - k * 120_000 for k in range(5040)]  # the oldest is 6 d 23 h 58 min back: inside the 7 days
    await db.insert_telemetry([Telemetry(DEV, "volt", ts, 360.0, None, "rest") for ts in stamps])
    app, _ = make_app(db)
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        d = (await get_json(c, URL % DEV + "?days=7"))["data"]
    assert d["truncated"] is True and d["hourly"] is False
    assert len(d["volt"]) == SERIES_MAX_POINTS and d["rsrp"] == []
    ats = [int(parse_iso(p["at"]).timestamp() * 1000) for p in d["volt"]]
    assert ats == sorted(ats)  # still oldest first
    assert ats[-1] == newest  # the newest reading is the last point (a head slice would end 5040-1500 readings earlier)
    assert ats[0] == newest - (SERIES_MAX_POINTS - 1) * 120_000  # and exactly the newest 1500 are kept


async def test_a_manhole_without_readings_has_two_empty_series(db):
    await mk_series(db)
    app, _ = make_app(db)
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        for days in (7, 30):
            d = (await get_json(c, URL % (PFX + "series-empty") + "?days=%d" % days))["data"]
            assert d["volt"] == [] and d["rsrp"] == [] and d["truncated"] is False


@pytest.mark.parametrize("qs", ["days=1", "days=6", "days=8", "days=29", "days=31", "days=0", "days=-7", "days=7.0", "days=x", "days="])
async def test_days_other_than_7_or_30_is_400(db, qs):
    await mk_series(db)
    app, _ = make_app(db)
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        r = await c.get(URL % DEV + "?" + qs, headers=AUTH)
        assert r.status == 400 and await r.json() == {"error": "days must be 7 or 30"}, qs


async def test_unknown_ids_are_404_and_bad_ids_400(db):
    await mk_series(db)
    app, _ = make_app(db)
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        assert (await c.get(URL % (PFX + "nobody"), headers=AUTH)).status == 404
        assert (await c.get(URL % (PFX + "series-gps"), headers=AUTH)).status == 404  # a tracker is not a manhole
        assert (await c.get(URL % "bad%20id", headers=AUTH)).status == 400
        assert (await c.get(URL % (PFX + "nobody") + "?days=99", headers=AUTH)).status == 400  # parameters before lookup


async def test_scopes_401_403_and_sessions(db, tmp_path):
    await mk_series(db)
    keys = {n: secrets.token_hex(12) for n in ("iot", "poi", "status")}
    scopes = {"iot": ["iot:read"], "poi": ["poi:read"], "status": ["status:read"]}
    app, cfg = make_app(db, tmp_path, [_entry(n, keys[n], scopes[n]) for n in keys])
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        url = URL % DEV
        assert (await c.get(url)).status == 401
        assert (await c.get(url, headers={"Authorization": "Bearer nope"})).status == 401
        assert (await c.get(url, headers={"Authorization": "Bearer " + keys["iot"]})).status == 200
        for name in ("poi", "status"):
            r = await c.get(url, headers={"Authorization": "Bearer " + keys[name]})
            assert r.status == 403 and await r.json() == {"error": "forbidden"}, name  # no data in the body
        for user in ("admin", "orange", "huawei"):
            assert (await c.get(url, headers=await login(c, cfg, user))).status == 200, user
        for method in ("POST", "PUT", "DELETE"):
            assert (await c.request(method, url, headers=AUTH)).status in (404, 405), method  # read-only
