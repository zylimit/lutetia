# risk: high
"""Phase 8 测试完整性补洞：DFX 场景 P-1（坐标不进日志）与登记文件样例。
- 在带坐标的合成库上把 /api/v1 每个资源（含错误路径）都请求一遍，抓全部日志（DEBUG，所有 logger），
  响应里确实带坐标（证明数据走过）而日志里没有坐标对、没有写出坐标字面值、没有 lat / lon 字样。
- callers/example.json.sample 必须能过登记文件校验（README 指它作格式样例，样例坏了照抄的人启动失败）。"""
import logging
import re
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from test_api_v1_resources import (  # noqa: F401  (db is a fixture, pulled in by name)
    AUTH, PFX, db, fall_events_of, get_json, make_app, mk_bundles, mk_pois, ms_ago, twelve_manholes)
from lutetia.models import GpsPosition
from lutetia.web.callers import parse_callers

PAIR = re.compile(r"[0-9]{1,2}\.[0-9]{4,},\s*-?[0-9]{1,3}\.[0-9]{4,}")  # the acceptance grep of DEV-PLAN Phase 8
LITERALS = ("22.54321", "114.04567", "48.8566", "2.3522")
WORDS = re.compile(r"\b(lat|lon|lng|latitude|longitude)\b", re.I)
SAMPLE = Path(__file__).resolve().parent.parent / "callers" / "example.json.sample"


def _fix(dev, minutes, k):
    ts = ms_ago(minutes)
    return GpsPosition(dev, ts, ts, ts, 22.543210 + k * 0.001234, 114.045670 + k * 0.002345, 0.0, 0, 0.0, 0.0, 0, 0, None, None, 0,
                       None, None, None, None, "poll", {})


async def test_no_coordinates_in_any_log_line_while_every_v1_resource_is_served(db, caplog):
    ids = await twelve_manholes(db)  # manhole 8 carries attribute coordinates 48.85660 / 2.35220
    trackers = await mk_bundles(db)
    await db.insert_gps_positions([_fix(trackers["online"], 5 + 30 * k, k) for k in range(6)])
    await mk_pois(db)
    await fall_events_of(db, ids["quiet_8"], 2)
    caplog.set_level(logging.DEBUG)
    async with TestClient(TestServer(make_app(db)[0])) as c:
        bodies = []
        for path in ("/api/v1/summary", "/api/v1/manholes", "/api/v1/fall-events", "/api/v1/bundles", "/api/v1/pois",
                     "/api/v1/collector-status", "/api/v1/bundles/%s/track?days=7" % trackers["online"],
                     "/api/v1/pois/%sp1/segments" % PFX, "/api/v1/devices", "/api/v1/status",
                     "/api/v1/positions?device_id=%s" % trackers["online"]):
            r = await c.get(path, headers=AUTH)
            assert r.status == 200, (path, r.status)
            bodies.append(await r.text())
        for path in ("/api/v1/manholes?cursor=!!!", "/api/v1/bundles/nope/track", "/api/v1/pois/nope/segments"):
            assert (await c.get(path, headers=AUTH)).status in (400, 404), path
        await get_json(c, "/api/v1/manholes?limit=1")
    blob = "\n".join(bodies)
    assert "48.8566" in blob and "22.54" in blob, "responses must carry the coordinates, else this test proves nothing"
    lines = ["%s %s" % (r.name, r.getMessage()) for r in caplog.records]
    assert sum(1 for line in lines if " api caller=" in line) >= 14, "the api log lines were not captured"
    text = "\n".join(lines)
    assert not PAIR.search(text), PAIR.findall(text)
    assert [lit for lit in LITERALS if lit in text] == []
    assert not WORDS.search(text), WORDS.findall(text)


def test_example_sample_passes_the_registry_validator():
    callers = parse_callers(SAMPLE.read_text(encoding="utf-8"))
    assert [c.name for c in callers] == ["ofr", "monitoring"]
    assert callers[0].scopes == frozenset({"iot:read", "poi:read"}) and callers[1].scopes == frozenset({"status:read"})
