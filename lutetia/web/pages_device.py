"""Device detail page: header, chart / map containers, latest rows and attributes. Charts and map are drawn by /static/device.js."""
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from aiohttp import web

from ..db import max_age_hours
from .auth import require_session
from .html import esc, fmt_ago, fmt_ts, page, table
from .jsonutil import validate_device_id

SOURCES = ("dingtek", "gps51")
KIND_NAMES = {"dingtek": "Dingtek 井盖", "gps51": "GPS51 定位器"}


def _not_found() -> web.HTTPNotFound:
    return web.HTTPNotFound(text="<!doctype html><title>404</title><p>设备不存在</p>", content_type="text/html")


def _num(v: Any) -> Any:
    return v if v is not None else ""


async def _dingtek_body(db: Any, dev: str) -> Tuple[str, Optional[datetime]]:
    rows = await db.query_telemetry(dev, None, None, None, 50)
    attrs = await db.device_attributes(dev)
    latest = table(["时间", "key", "值", "原始值", "origin"],
                   [[fmt_ts(r["ts"]), r["key"], _num(r["value_si"] if r["value_si"] is not None else r["value_str"]),
                     _num(r["value_num"]), r["origin"]] for r in rows])
    attr = table(["key", "value", "更新时间"], [[a["key"], a["value"], fmt_ts(a["last_update_ts"])] for a in attrs])
    period = '<p class="period"><a href="?days=7">7 天</a> · <a href="?days=30">30 天</a></p>'
    charts = "".join('<h3>%s</h3><div class="chart"><canvas id="chart-%s"></canvas></div>' % (t, k)
                     for k, t in (("volt", "电压 (V)"), ("temperature", "温度"), ("rsrp", "信号 rsrp (dBm)")))
    return (period + charts + '<p id="chart-note"></p><h2>最近上报</h2>' + latest + "<h2>属性</h2>" + attr,
            rows[0]["ts"] if rows else None)


async def _gps_body(db: Any, dev: str) -> Tuple[str, Optional[datetime]]:
    rows = await db.query_positions(dev, None, None, 50)
    if rows:
        top = rows[0]
        stats = "<p>里程表 %s km · 运动 %s · 最后位置 %s · 来源 %s</p>" % (
            esc(top["total_distance_km"]), esc({True: "是", False: "否"}.get(top["moving"], "?")),
            esc(fmt_ts(top["update_time"])), esc(top["origin"]))
    else:
        stats = "<p>暂无位置</p>"
    pos = table(["时间", "lat", "lon", "speed_kmh", "origin"],
                [[fmt_ts(r["update_time"]), r["lat"], r["lon"], r["speed_kmh"], r["origin"]] for r in rows])
    return ('<div id="map"></div><p id="chart-note"></p>'
            '<p class="attrib">地图 © Google（测试阶段直拉瓦片，不商用）</p>' + stats + "<h2>最近位置</h2>" + pos,
            rows[0]["update_time"] if rows else None)


@require_session
async def device_page(request: web.Request) -> web.Response:
    source, dev = request.match_info["source"], request.match_info["device_id"]
    if source not in SOURCES or validate_device_id(dev) is not None:
        raise _not_found()
    db = request.app["ctx"].db
    device = await db.get_device(source, dev)
    if device is None:
        raise _not_found()
    days = request.query.get("days", "")
    days = days if days in ("7", "30") else "7"
    now = datetime.now(timezone.utc)
    if source == "dingtek":
        content, last = await _dingtek_body(db, dev)
        head, scripts = "", '<script src="/static/vendor/chart.umd.js" defer></script><script src="/static/device.js" defer></script>'
    else:
        content, last = await _gps_body(db, dev)
        head = '<link rel="stylesheet" href="/static/vendor/leaflet.css">'
        scripts = '<script src="/static/vendor/leaflet.js" defer></script><script src="/static/device.js" defer></script>'
    name = device["name"] or dev
    online = {True: "是", False: "否"}.get(device["expected_online"], "?")
    sub = "<p>类型 %s · 应在线 %s · 最后入库 %s · 距今 %s</p>" % (
        esc(device["device_type"] or KIND_NAMES[source]), online, esc(fmt_ts(last)), esc(fmt_ago(last, now)))
    body = ('<p><a href="/dashboard/">← 看板</a></p><h1>%s（%s）</h1>%s<div id="device" data-kind="%s" data-device-id="%s" data-days="%s">%s</div>'
            % (esc(name), esc(dev), sub, esc(source), esc(dev), days, content))
    return page(str(name), body, head=head, scripts=scripts)


def register_device_pages(app: web.Application) -> None:
    app.router.add_get("/dashboard/device/{source}/{device_id}", device_page)
