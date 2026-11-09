# risk: high
"""/api/v1 summary count invariants on random manhole mixes (Phase 8 Task 8.3; rules of 2026-11-10: inactive counted apart,
offline stays offline with an open event, the three status bands are mutually exclusive and add up to the in-use total).
Three seeded groups of 15-30 synthetic manholes (zz-test-sum-*, removed after) mixing expected_online true / false / NULL,
telemetry online / offline / none and events none / open / ended < 24 h ago / ended > 24 h ago. The expected status of every
device is worked out here from the rules, not by calling the code under test. Real local database (DATABASE_URL), else skip."""
import os
import random
import time
from datetime import timedelta

import pytest
from aiohttp.test_utils import TestClient, TestServer

import lutetia.cli
from lutetia.config import load_dotenv
from lutetia.db import Database
from lutetia.models import Attribute, Device, Telemetry
from test_api_v1_resources import AUTH, get_json, make_app

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
PFX = "zz-test-sum-"
SEEDS = (20261110, 20261111, 20261112)
STATUSES = ("inactive", "offline", "moving", "moved", "quiet")
GUARD_H = 2 / 60  # no timestamp closer than 2 minutes to a rule boundary, so the seconds between "now" here and in the app cannot flip a status


def build_group(seed):
    """-> list of dicts {id, expected, interval, last_h, ev: (kind, nonzero_h, zero_h|None), status, open_event}; *_h are hours before `now`."""
    rng = random.Random(seed)
    devs = []
    for i in range(rng.randint(15, 30)):
        expected = rng.choice([True, True, True, False, None])
        interval = rng.choice([None, None, 2, 4, 12])
        limit_h = max(3.0, 2.0 * (interval or 0))
        tel = rng.choice(["online", "offline", "none"])
        ev_kind = rng.choice(["none", "open", "recent", "old"]) if tel != "none" else "none"  # events are derived from telemetry
        last_h = None
        if tel == "online":
            last_h = rng.uniform(0.2, limit_h - 1.0)
        elif tel == "offline":
            last_h = limit_h + rng.uniform(1.0, 10.0)
        ev = (ev_kind, None, None)
        if ev_kind != "none":
            floor = last_h + 0.2  # events never newer than the last volt reading, so last_ts is the volt reading
            if ev_kind == "open":
                ev = (ev_kind, max(rng.uniform(1.0, 20.0), floor), None)
            else:
                zero = max(rng.uniform(0.5, 22.0) if ev_kind == "recent" else rng.uniform(26.0, 40.0), floor)
                ev = (ev_kind, zero + rng.uniform(0.1, 1.0), zero)
        d = {"id": "%sg%d-%02d" % (PFX, seed % 10, i), "expected": expected, "interval": interval, "limit_h": limit_h,
             "last_h": last_h, "ev": ev}
        # expected status from the rules: inactive first, then offline, moving, moved, quiet
        open_ev = ev[1] is not None and ev[2] is None
        ended_recent = ev[2] is not None and ev[2] < 24.0
        if expected is not True:
            d["status"] = "inactive"
        elif last_h is None or last_h > limit_h:
            d["status"] = "offline"
        elif open_ev:
            d["status"] = "moving"
        elif ended_recent:
            d["status"] = "moved"
        else:
            d["status"] = "quiet"
        d["open_event"] = open_ev
        if last_h is not None:
            assert abs(last_h - limit_h) > GUARD_H, d
        if ev[2] is not None:
            assert abs(ev[2] - 24.0) > GUARD_H, d
        devs.append(d)
    return devs


def test_generator_covers_every_status_and_the_open_event_offline_case():
    """Guards the guard: the three seeded groups together must hit every status and the offline + open event combination."""
    allv = [d for s in SEEDS for d in build_group(s)]
    assert {d["status"] for d in allv} == set(STATUSES)
    assert any(d["status"] == "offline" and d["open_event"] for d in allv)
    assert any(d["status"] == "inactive" and d["expected"] is None for d in allv)
    assert any(d["status"] == "inactive" and d["expected"] is False for d in allv)
    assert all(15 <= len(build_group(s)) <= 30 for s in SEEDS)


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
    async with d.pool.acquire() as conn:
        for t in ("sensor_telemetry", "sensor_attribute", "device"):
            await conn.execute("DELETE FROM %s WHERE device_id LIKE $1" % t, PFX + "%")  # table names are literals above


async def seed_group(db, devs, now_s):
    def ms(h):
        return int((now_s - h * 3600) * 1000)
    await db.upsert_devices([Device("dingtek", d["id"], d["id"], "DC414", d["expected"], {}) for d in devs])
    rows, attrs = [], []
    for d in devs:
        if d["interval"]:
            attrs.append(Attribute(d["id"], "uploadInterval", "%dh" % d["interval"], None))
        if d["last_h"] is not None:
            rows += [Telemetry(d["id"], "volt", ms(d["last_h"]), 372.0, None, "rest"), Telemetry(d["id"], "rsrp", ms(d["last_h"]), -950.0, None, "rest")]
        kind, nz, zero = d["ev"]
        if kind != "none":
            rows.append(Telemetry(d["id"], "alarmFall", ms(nz), 1.0, None, "rest"))
            if zero is not None:
                rows.append(Telemetry(d["id"], "alarmFall", ms(zero), 0.0, None, "rest"))
    await db.insert_telemetry(rows)
    await db.upsert_attributes(attrs)


@pytest.mark.parametrize("seed", SEEDS)
async def test_summary_counts_hold_on_a_random_group(db, seed):
    devs = build_group(seed)
    async with TestClient(TestServer(make_app(db)[0])) as c:
        base = (await get_json(c, "/api/v1/summary"))["data"]["manholes"]
        await seed_group(db, devs, time.time())
        m0 = (await get_json(c, "/api/v1/summary"))["data"]["manholes"]
        listing = await get_json(c, "/api/v1/manholes?limit=1000")
    assert listing["next"] is None  # all rows fetched in one page
    items = listing["items"]
    by_id = {i["device_id"]: i for i in items}

    # every device: status and open_event equal the independently derived values
    for d in devs:
        got = by_id[d["id"]]
        assert (got["status"], got["open_event"]) == (d["status"], d["open_event"]), d

    # whole-database invariants
    m = {k: v for k, v in m0.items()}
    assert m["moved_24h"] + m["offline"] + m["quiet"] == m["total"]
    assert m["total"] + m["inactive"] == m["all"]
    assert m["moving"] <= m["moved_24h"]
    assert m["offline_with_open_event"] <= m["offline"]
    # summary equals the status tally of the listing
    tally = {s: sum(1 for i in items if i["status"] == s) for s in STATUSES}
    assert m["inactive"] == tally["inactive"] and m["offline"] == tally["offline"] and m["quiet"] == tally["quiet"]
    assert m["moving"] == tally["moving"] and m["moved_24h"] == tally["moving"] + tally["moved"]
    assert m["all"] == len(items)
    assert m["offline_with_open_event"] == sum(1 for i in items if i["status"] == "offline" and i["open_event"])
    # and the delta this group added equals what the independent model says
    want = {s: sum(1 for d in devs if d["status"] == s) for s in STATUSES}
    assert m0["inactive"] - base["inactive"] == want["inactive"]
    assert m0["offline"] - base["offline"] == want["offline"]
    assert m0["quiet"] - base["quiet"] == want["quiet"]
    assert m0["moving"] - base["moving"] == want["moving"]
    assert m0["moved_24h"] - base["moved_24h"] == want["moving"] + want["moved"]
    assert m0["all"] - base["all"] == len(devs)
    assert m0["offline_with_open_event"] - base["offline_with_open_event"] == sum(1 for d in devs if d["status"] == "offline" and d["open_event"])
