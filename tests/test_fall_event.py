# risk: high
"""Phase 7 Task 7.1: fall_event view merges alarmFall flips within 30 minutes (SC-13), on synthetic telemetry."""
import os
from datetime import datetime, timedelta, timezone

import pytest

import lutetia.cli
from lutetia.config import load_dotenv
from lutetia.db import Database

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
PFX = "zz-test-fall-"
T0 = datetime(2026, 1, 5, 8, 0, 0, tzinfo=timezone.utc)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


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
    async with d.pool.acquire() as conn:
        await conn.execute("DELETE FROM sensor_telemetry WHERE device_id LIKE $1", PFX + "%")
    yield d
    async with d.pool.acquire() as conn:
        await conn.execute("DELETE FROM sensor_telemetry WHERE device_id LIKE $1", PFX + "%")
    await d.close()


async def load(db, device, points, key="alarmFall"):
    """points: [(minutes_from_T0, value)]; value may be number, 'true'/'false' (stored as value_str) or None."""
    rows = []
    for m, v in points:
        num = v if isinstance(v, (int, float)) else None
        txt = v if isinstance(v, str) else None
        rows.append((PFX + device, key, at(m), num, txt, "rest"))
    async with db.pool.acquire() as conn:
        await conn.executemany(
            "INSERT INTO sensor_telemetry (device_id, key, ts, value_num, value_str, origin) VALUES ($1,$2,$3,$4,$5,$6)", rows)


async def events(db, device=None):
    async with db.pool.acquire() as conn:
        rows = await conn.fetch("SELECT device_id, started_at, ended_at, flips FROM fall_event "
                                "WHERE device_id LIKE $1 ORDER BY device_id, started_at", PFX + (device or "") + "%")
    return [(r["started_at"], r["ended_at"], r["flips"]) for r in rows]


async def test_spec_example_three_flips_one_event(db):
    await load(db, "a", [(0, 1), (10, 0), (20, 1), (30, 0), (45, 1), (50, 0)])
    assert await events(db, "a") == [(at(0), at(50), 3)]


async def test_gap_29_minutes_between_nonzero_is_one_event(db):
    await load(db, "a", [(0, 1), (5, 0), (29, 1), (35, 0)])
    assert await events(db, "a") == [(at(0), at(35), 2)]


async def test_gap_31_minutes_between_nonzero_is_two_events(db):
    await load(db, "a", [(0, 1), (5, 0), (31, 1), (35, 0)])
    assert await events(db, "a") == [(at(0), at(5), 1), (at(31), at(35), 1)]


async def test_gap_exactly_30_minutes_merges(db):
    await load(db, "a", [(0, 1), (5, 0), (30, 1), (40, 0)])
    assert await events(db, "a") == [(at(0), at(40), 2)]


async def test_spec_example_third_flip_at_51_makes_two_events(db):
    await load(db, "a", [(0, 1), (10, 0), (20, 1), (30, 0), (51, 1), (55, 0)])
    assert await events(db, "a") == [(at(0), at(30), 2), (at(51), at(55), 1)]


async def test_unfinished_event_has_null_ended_at(db):
    await load(db, "a", [(0, 1), (10, 0), (100, 1)])
    assert await events(db, "a") == [(at(0), at(10), 1), (at(100), None, 1)]


async def test_consecutive_nonzero_counts_one_flip(db):
    await load(db, "a", [(0, 0), (5, 1), (10, 1), (15, 1), (20, 0)])
    assert await events(db, "a") == [(at(5), at(20), 1)]


async def test_first_row_nonzero_counts_as_flip(db):
    await load(db, "a", [(0, 1), (5, 0)])
    assert await events(db, "a") == [(at(0), at(5), 1)]


async def test_sparse_nonzero_rows_without_zero_between_is_one_event(db):
    await load(db, "a", [(0, 1), (60, 1), (70, 0)])
    assert await events(db, "a") == [(at(0), at(70), 1)]


async def test_hourly_heartbeats_while_cover_stays_open_is_one_event(db):
    # Q-1: 08:00 / 09:00 / 10:00 all report 1, back to 0 at 11:00 -> one event, one flip
    await load(db, "a", [(0, 1), (60, 1), (120, 1), (180, 0)])
    assert await events(db, "a") == [(at(0), at(180), 1)]


async def test_open_cover_with_61_minute_heartbeats_then_new_flip_later(db):
    await load(db, "a", [(0, 1), (61, 1), (122, 1), (183, 0), (190, 1), (195, 0)])
    assert await events(db, "a") == [(at(0), at(183), 1), (at(190), at(195), 1)]


async def test_never_closed_cover_stays_one_open_event(db):
    await load(db, "a", [(0, 1), (61, 1), (122, 1)])
    assert await events(db, "a") == [(at(0), None, 1)]


async def test_gap_30_minutes_01_seconds_makes_two_events(db):
    await load(db, "a", [(0, 1), (5, 0), (30 + 1 / 60.0, 1), (40, 0)])
    got = await events(db, "a")
    assert len(got) == 2 and [g[2] for g in got] == [1, 1]
    assert got[0][1] == at(5) and got[1][2] == 1


async def test_gap_measured_from_last_nonzero_row_not_from_first_edge(db):
    # nonzero at 0 and 10, zero at 15, edge at 40: 30 min after the last nonzero (10) -> merge, flips=2
    await load(db, "a", [(0, 1), (10, 1), (15, 0), (40, 1), (45, 0)])
    assert await events(db, "a") == [(at(0), at(45), 2)]
    await load(db, "b", [(0, 1), (10, 1), (15, 0), (40.02, 1), (45, 0)])
    assert len(await events(db, "b")) == 2


async def test_boolean_strings_mixed_with_numbers_and_case(db):
    await load(db, "a", [(0, "TRUE"), (5, "false"), (10, 1), (12, 0), (14, "True"), (16, "FALSE")])
    assert await events(db, "a") == [(at(0), at(16), 3)]


async def test_cover_tilted_with_61_minute_heartbeats_24_times_then_zero_is_one_flip(db):
    pts = [(61 * i, 1) for i in range(24)] + [(61 * 23 + 61, 0)]
    await load(db, "a", pts)
    assert await events(db, "a") == [(at(0), at(61 * 24), 1)]


def rising_edges(points):
    prev, out = 0, []
    for m, v in sorted(points):
        if v != 0 and prev == 0:
            out.append(at(m))
        prev = v
    return out


async def test_every_rising_edge_lands_in_exactly_one_event_and_events_never_overlap(db):
    series = {
        "a": [(0, 0), (3, 1), (4, 0), (40, 1), (41, 0), (45, 1), (47, 0), (200, 1), (201, 0)],
        "b": [(0, 1), (1, 1), (2, 0), (31, 1), (32, 0), (62, 1), (63, 0), (64, 1)],
        "c": [(0, 0), (10, 0), (20, 0)],
        "d": [(0, 1), (30, 0), (59, 1), (60, 0), (91, 1), (92, 0), (122, 1), (123, 0), (153, 1)],
        "e": [(0, 1), (60, 1), (120, 1), (180, 0), (181, 1), (300, 1), (361, 1), (362, 0)],   # sparse, long-open
        "f": [(0, 1), (10, 0), (20, 1), (30, 0), (51, 1), (60, 1), (130, 1), (131, 0), (150, 1)],
    }
    for dev, pts in series.items():
        await load(db, dev, pts)
        evs = await events(db, dev)
        inf = datetime.max.replace(tzinfo=timezone.utc)
        for earlier, later in zip(evs, evs[1:]):
            assert (earlier[1] or inf) <= later[0], "events overlap on %s: %s" % (dev, evs)
        edges = rising_edges(pts)
        assert [e for e in edges if not any(s <= e < (end or inf) for s, end, _ in evs)] == [], dev
        for s, end, flips in evs:
            assert flips == len([e for e in edges if s <= e < (end or inf)]), (dev, evs)
        assert sum(f for _, _, f in evs) == len(edges), dev
    assert await events(db, "c") == []


async def test_devices_are_independent(db):
    await load(db, "a", [(0, 1), (5, 0)])
    await load(db, "b", [(10, 1), (15, 0)])
    assert await events(db, "a") == [(at(0), at(5), 1)]
    assert await events(db, "b") == [(at(10), at(15), 1)]


async def test_boolean_strings_and_other_keys_and_garbage(db):
    await load(db, "a", [(0, "true"), (5, "false"), (9, "garbage")])
    await load(db, "a", [(1, 1)], key="alarmBattery")
    assert await events(db, "a") == [(at(0), at(5), 1)]
