"""Login pages and the read-only dashboard (server-rendered, every dynamic value escaped)."""
import html
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

from aiohttp import web

from ..db import max_age_hours
from .auth import COOKIE_NAME, check_password, client_ip, require_session

log = logging.getLogger(__name__)

def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def fmt_ts(ts: Optional[datetime]) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if ts else "-"


def fmt_ago(ts: Optional[datetime], now: datetime) -> str:
    if ts is None:
        return "-"
    minutes = max(0, int((now - ts).total_seconds() // 60))
    if minutes < 60:
        return "%d 分钟" % minutes
    if minutes < 24 * 60:
        return "%d 小时" % (minutes // 60)
    return "%d 天" % (minutes // (24 * 60))


def fmt_secs(sec: float) -> str:
    return fmt_ago(datetime.now(timezone.utc) - timedelta(seconds=sec), datetime.now(timezone.utc))


def page(title: str, body: str, script: bool = False) -> web.Response:
    js = '<script src="/static/app.js" defer></script>' if script else ""
    doc = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
           '<title>%s</title><link rel="stylesheet" href="/static/app.css"></head><body>%s%s</body></html>'
           % (esc(title), body, js))
    return web.Response(text=doc, content_type="text/html")


def table(headers: List[str], rows: List[List[Any]], row_class: Optional[List[str]] = None, tbody_id: str = "", cards: bool = False) -> str:
    out = [("<table class=\"cards\">" if cards else "<table>") + "<thead><tr>" + "".join("<th>%s</th>" % esc(h) for h in headers) + "</tr></thead>",
           '<tbody id="%s">' % esc(tbody_id) if tbody_id else "<tbody>"]
    for i, r in enumerate(rows):
        cls = ' class="%s"' % row_class[i] if row_class and row_class[i] else ""
        out.append("<tr%s>" % cls + "".join('<td data-label="%s">%s</td>' % (esc(headers[j] if j < len(headers) else ""), esc(c))
                                          for j, c in enumerate(r)) + "</tr>")
    return "".join(out) + "</tbody></table>"


def login_page(message: str = "", next_url: str = "", status: int = 200) -> web.Response:
    msg = "<p>%s</p>" % esc(message) if message else ""
    body = ('<h1>Lutetia 登录</h1>%s<form method="post" action="/login">'
            '<input type="hidden" name="next" value="%s">'
            '<p><label>账号 <input name="username" autofocus></label></p>'
            '<p><label>密码 <input name="password" type="password"></label></p>'
            '<p><button type="submit">登录</button></p></form>' % (msg, esc(next_url)))
    resp = page("Lutetia 登录", body)
    resp.set_status(status)
    return resp


def safe_next(target: str) -> str:
    """Only same-site absolute paths; anything else falls back to the dashboard."""
    parts = urlsplit(target or "")
    if target.startswith("/") and not target.startswith("//") and not parts.netloc and "\\" not in target:
        return target
    return "/dashboard/"


async def root(request: web.Request) -> web.Response:
    raise web.HTTPFound("/dashboard/")


async def login_get(request: web.Request) -> web.Response:
    return login_page(next_url=safe_next(request.query.get("next", "")))


async def login_post(request: web.Request) -> web.Response:
    ctx = request.app["ctx"]
    ip = client_ip(request, ctx.cfg.trust_proxy)
    form = await request.post()
    next_url = safe_next(str(form.get("next", "")))
    if ctx.limiter.is_globally_locked() or ctx.limiter.is_locked(ip):
        log.warning("web login: ip %s locked", ip)
        return login_page("尝试次数过多，请稍后再试", next_url, 429)
    ok_user = str(form.get("username", "")) == ctx.cfg.dashboard_user
    ok_pwd = check_password(str(form.get("password", "")), ctx.cfg.dashboard_pwd)
    if not (ok_user and ok_pwd):
        ctx.limiter.record_failure(ip)
        log.warning("web login: failed attempt from %s", ip)
        return login_page("账号或密码错误", next_url, 401)
    ctx.limiter.reset(ip)
    resp = web.HTTPFound(next_url)
    secure = request.headers.get("X-Forwarded-Proto") == "https" or request.scheme == "https"
    resp.set_cookie(COOKIE_NAME, ctx.signer.issue(ctx.cfg.dashboard_user), httponly=True,
                    samesite="Lax", max_age=43200, secure=secure)
    raise resp


async def logout(request: web.Request) -> web.Response:
    request.app["ctx"].signer.revoke(request.cookies.get(COOKIE_NAME, ""))
    resp = web.HTTPFound("/login")
    resp.del_cookie(COOKIE_NAME)
    raise resp


def devices_section(rows: List[Dict[str, Any]], now: datetime) -> str:
    cells, classes = [], []
    for r in rows:
        last = r["last_ts"]
        limit = max_age_hours(3.0, r["upload_interval_h"])
        stale = bool(r["expected_online"]) and (last is None or now - last > timedelta(hours=limit))
        online = {True: "是", False: "否"}.get(r["expected_online"], "?")
        cells.append([r["source"], r["device_id"], r["name"], r["device_type"], online,
                      fmt_ts(last), fmt_ago(last, now), "STALE" if stale else ""])
        classes.append("stale" if stale else "")
    return "<h2>设备总览</h2>" + table(
        ["source", "device_id", "名字", "类型", "应在线", "最后入库", "距今", "状态"], cells, classes, "tbl-devices", cards=True)


def sensors_section(rows: List[Dict[str, Any]]) -> str:
    by_dev: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = by_dev.setdefault(r["device_id"], {"name": r["name"], "ts": r["ts"]})
        d[r["key"]] = r["value_si"] if r["value_si"] is not None else (r["value_num"] if r["value_num"] is not None else r["value_str"])
        if r["ts"] > d["ts"]:
            d["ts"] = r["ts"]
    cells = [[d["name"], dev, d.get("volt"), d.get("temperature"), d.get("rsrp"), fmt_ts(d["ts"])]
             for dev, d in sorted(by_dev.items(), key=lambda kv: str(kv[1]["name"]))]
    return "<h2>最新读数</h2>" + table(["名字", "device_id", "volt (V)", "temperature", "rsrp (dBm)", "时间"], cells, tbody_id="tbl-sensor", cards=True)


def gps_section(rows: List[Dict[str, Any]]) -> str:
    cells = [[r["name"], r["device_id"], fmt_ts(r["update_time"]), r["lat"], r["lon"], r["speed_kmh"], r["origin"]] for r in rows]
    return "<h2>最后位置</h2>" + table(["名字", "device_id", "时间", "lat", "lon", "speed_kmh", "origin"], cells, tbody_id="tbl-gps")


def collector_section(ctx: Any, calls: List[Dict[str, Any]], now: datetime) -> str:
    rcv = ctx.receiver
    if rcv is None:
        rec = "<p>推送接收端未启用</p>"
    else:
        queued = rcv.queue.qsize() if hasattr(rcv, "queue") else getattr(rcv, "queued", 0)
        pairs = [(k, getattr(rcv, k)) for k in ("received", "stored", "rejected", "unrecognised", "alarms", "failed")]
        pairs += [("queued", queued), ("silent", fmt_secs(rcv.silent_for())), ("message_silent", fmt_secs(rcv.message_silent_for()))]
        rec = table([k for k, _ in pairs], [[v for _, v in pairs]], tbody_id="tbl-receiver")
    api = table(["source", "action", "24h 调用数"], [[c["source"], c["action"], c["n"]] for c in calls], tbody_id="tbl-calls")
    info = '<p>服务启动 %s · <span id="last-refresh">生成于 %s</span></p>' % (esc(fmt_ts(ctx.started_at)), esc(fmt_ts(now)))
    return "<h2>采集器状态</h2>" + rec + api + info


@require_session
async def dashboard(request: web.Request) -> web.Response:
    ctx = request.app["ctx"]
    now = datetime.now(timezone.utc)
    status = await ctx.db.device_status()
    sensors = await ctx.db.latest_sensor_values(("volt", "temperature", "rsrp"))
    gps = await ctx.db.latest_gps_positions()
    calls = await ctx.db.call_summary(24)
    body = ('<p><a href="/logout">退出</a></p><h1>Lutetia 看板</h1><div id="anomalies"></div>' + devices_section(status, now)
            + sensors_section(sensors) + gps_section(gps) + collector_section(ctx, calls, now))
    return page("Lutetia 看板", body, script=True)


def register_dashboard(app: web.Application) -> None:
    app.router.add_get("/", root)
    app.router.add_get("/login", login_get)
    app.router.add_post("/login", login_post)
    app.router.add_get("/logout", logout)
    app.router.add_get("/dashboard/", dashboard)
