"""Device detail page: header, chart / map containers, latest rows and attributes. Charts and map are drawn by /static/device.js."""
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

from aiohttp import web

from ..db import max_age_hours
from .auth import require_admin
from .dashboard import yes_no
from .html import esc, fmt_ago, fmt_ts, ops_header, page, table
from .i18n import pick_lang, t
from .jsonutil import validate_device_id
from .pages_map import OSM_ATTRIBUTION

SOURCES = ("dingtek", "gps51")


def _not_found(lang: str) -> web.HTTPNotFound:
    return web.HTTPNotFound(text="<!doctype html><title>404</title><p>%s</p>" % esc(t(lang, "dev.notfound")), content_type="text/html")


def _num(v: Any) -> Any:
    return v if v is not None else ""


async def _dingtek_body(db: Any, dev: str, lang: str) -> Tuple[str, Optional[datetime]]:
    rows = await db.query_telemetry(dev, None, None, None, 50)
    attrs = await db.device_attributes(dev)
    latest = table([t(lang, "col.time"), "key", t(lang, "col.value"), t(lang, "col.raw"), "origin"],
                   [[fmt_ts(r["ts"]), r["key"], _num(r["value_si"] if r["value_si"] is not None else r["value_str"]),
                     _num(r["value_num"]), r["origin"]] for r in rows])
    attr = table(["key", "value", t(lang, "col.updated")], [[a["key"], a["value"], fmt_ts(a["last_update_ts"])] for a in attrs])
    period = '<p class="period"><a href="?days=7">%s</a> · <a href="?days=30">%s</a></p>' % (esc(t(lang, "dev.days7")), esc(t(lang, "dev.days30")))
    charts = "".join('<h3>%s</h3><div class="chart"><canvas id="chart-%s"></canvas></div>' % (esc(t(lang, "chart." + k)), k)
                     for k in ("volt", "temperature", "rsrp"))
    return (period + charts + '<p id="chart-note"></p><h2>%s</h2>' % esc(t(lang, "sec.latest")) + latest
            + "<h2>%s</h2>" % esc(t(lang, "sec.attrs")) + attr, rows[0]["ts"] if rows else None)


async def _gps_body(db: Any, dev: str, lang: str) -> Tuple[str, Optional[datetime]]:
    rows = await db.query_positions(dev, None, None, 50)
    if rows:
        top = rows[0]
        stats = "<p>%s</p>" % esc(t(lang, "gps.stats", km=t(lang, "gps.nokm") if top["total_distance_km"] is None else "%s km" % top["total_distance_km"], moving=yes_no(top["moving"], lang),
                                    t=fmt_ts(top["update_time"]), origin=top["origin"]))
    else:
        stats = "<p>%s</p>" % esc(t(lang, "pos.none"))
    pos = table([t(lang, "col.time"), "lat", "lon", "speed_kmh", "origin"],
                [[fmt_ts(r["update_time"]), r["lat"], r["lon"], r["speed_kmh"], r["origin"]] for r in rows])
    return ('<div id="map"></div><p id="chart-note"></p>'
            '<p class="attrib">%s %s</p>' % (esc(t(lang, "map.base")), OSM_ATTRIBUTION) + stats
            + "<h2>%s</h2>" % esc(t(lang, "sec.positions")) + pos, rows[0]["update_time"] if rows else None)


@require_admin
async def device_page(request: web.Request) -> web.Response:
    lang = pick_lang(request)
    source, dev = request.match_info["source"], request.match_info["device_id"]
    if source not in SOURCES or validate_device_id(dev) is not None:
        raise _not_found(lang)
    db = request.app["ctx"].db
    device = await db.get_device(source, dev)
    if device is None:
        raise _not_found(lang)
    days = request.query.get("days", "")
    days = days if days in ("7", "30") else "7"
    now = datetime.now(timezone.utc)
    if source == "dingtek":
        content, last = await _dingtek_body(db, dev, lang)
        head, scripts = "", '<script src="/static/vendor/chart.umd.js" defer></script><script src="/static/device.js" defer></script>'
    else:
        content, last = await _gps_body(db, dev, lang)
        head = '<link rel="stylesheet" href="/static/vendor/leaflet.css">'
        scripts = '<script src="/static/vendor/leaflet.js" defer></script><script src="/static/device.js" defer></script>'
    name = device["name"] or dev
    sub = "<p>%s</p>" % esc(t(lang, "dev.sub", type=device["device_type"] or t(lang, "kind." + source),
                              online=yes_no(device["expected_online"], lang), last=fmt_ts(last), age=fmt_ago(last, now, lang)))
    body = (ops_header(request, request["user"], ['<a href="/dashboard/">%s</a>' % esc(t(lang, "nav.board"))])
            + '<h1>%s (%s)</h1>%s<div id="device" data-kind="%s" data-device-id="%s" data-days="%s">%s</div>'
            % (esc(name), esc(dev), sub, esc(source), esc(dev), days, content))
    return page(request, str(name), body, head=head, scripts=scripts)


def register_device_pages(app: web.Application) -> None:
    app.router.add_get("/dashboard/device/{source}/{device_id}", device_page)
