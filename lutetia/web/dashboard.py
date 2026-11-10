"""Login pages and the read-only dashboard (server-rendered, every dynamic value escaped)."""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from aiohttp import web

from ..db import max_age_hours
from . import anomalies
from .data import build_anomalies, heartbeat_view
from .auth import COOKIE_NAME, authenticate, client_ip, is_admin, require_admin, safe_app_next
from .spa import is_spa_path
from .html import esc, fmt_ago, fmt_ts, ops_header, page, table

log = logging.getLogger(__name__)

def fmt_secs(sec: float) -> str:
    return fmt_ago(datetime.now(timezone.utc) - timedelta(seconds=sec), datetime.now(timezone.utc))


def login_page(message: str = "", next_url: str = "", status: int = 200) -> web.Response:
    msg = "<p>%s</p>" % esc(message) if message else ""
    body = ('<h1>Lutetia 登录</h1>%s<form method="post" action="/login">'
            '<input type="hidden" name="next" value="%s">'
            '<p><label>账号 <input name="username" autofocus autocapitalize="none" autocorrect="off" spellcheck="false" autocomplete="username"></label></p>'
            '<p><label>密码 <input name="password" type="password" autocomplete="current-password"></label></p>'
            '<p><label><input name="remember" type="checkbox" value="1"> 30 天内保持登录（Keep me signed in for 30 days）</label></p>'
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


def resolve_next(raw: str) -> Tuple[str, bool]:
    """(where to go after login, whether the request comes from the project dashboard SPA). A target under /app is accepted only
    when safe_app_next approves it; otherwise it falls back to the ops dashboard like any other unsafe target."""
    if is_spa_path(urlsplit(raw).path):
        ok = safe_app_next(raw)
        return (ok, True) if ok else ("/dashboard/", False)
    return safe_next(raw), False


def spa_signin_url(error: str, next_url: str) -> str:
    return "/app/signin?error=%s&next=%s" % (error, quote(next_url, safe=""))


async def root(request: web.Request) -> web.Response:
    """Site root: a signed-in admin goes to the ops dashboard; everyone else to the project dashboard (the SPA sends the
    signed-out to its own sign-in page)."""
    user = request.app["ctx"].signer.verify(request.cookies.get(COOKIE_NAME, ""))
    raise web.HTTPFound("/dashboard/" if user is not None and is_admin(request, user) else "/app/")


async def login_get(request: web.Request) -> web.Response:
    return login_page(next_url=safe_next(request.query.get("next", "")))


async def login_post(request: web.Request) -> web.Response:
    ctx = request.app["ctx"]
    ip = client_ip(request, ctx.cfg.trust_proxy)
    form = await request.post()
    next_url, from_spa = resolve_next(str(form.get("next", "")))
    if ctx.limiter.is_globally_locked() or ctx.limiter.is_locked(ip):
        log.warning("web login: ip %s locked", ip)
        if from_spa:
            raise web.HTTPSeeOther(spa_signin_url("locked", next_url))
        return login_page("尝试次数过多，请稍后再试", next_url, 429)
    user = authenticate(ctx.cfg.accounts(), str(form.get("username", "")), str(form.get("password", "")))
    if user is None:
        ctx.limiter.record_failure(ip)
        log.warning("web login: failed attempt from %s", ip)
        if from_spa:
            raise web.HTTPSeeOther(spa_signin_url("1", next_url))
        return login_page("账号或密码错误", next_url, 401)
    ctx.limiter.reset(ip)
    resp = web.HTTPFound(next_url)
    secure = request.headers.get("X-Forwarded-Proto") == "https" or request.scheme == "https"
    remember = str(form.get("remember", "")) == "1"
    resp.set_cookie(COOKIE_NAME, ctx.signer.issue(user, remember=remember), httponly=True,
                    samesite="Lax", max_age=ctx.signer.ttl_for(remember), secure=secure)
    log.info("web login: account %s signed in (remember=%s)", user, remember)
    raise resp


def _end_session(request: web.Request, raw_next: str) -> web.Response:
    request.app["ctx"].signer.revoke(request.cookies.get(COOKIE_NAME, ""))
    target = safe_app_next(raw_next) or "/login"  # the project dashboard asks to land on its own sign-in page
    resp = web.HTTPFound(target)
    resp.del_cookie(COOKIE_NAME)
    raise resp


async def logout(request: web.Request) -> web.Response:
    """GET stays for the ops dashboard's plain link. A browser that says the request came from another site
    (Sec-Fetch-Site present and neither same-origin nor none) only gets sent to /login: the session is not revoked, so a
    foreign page cannot sign anyone out with a top-level link (#110). No header (old browsers, scripts) keeps the old behaviour."""
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None and site not in ("same-origin", "none"):
        log.warning("web logout: cross-site GET not honoured (Sec-Fetch-Site=%r)", site)
        raise web.HTTPFound("/login")
    return _end_session(request, request.query.get("next", ""))


def same_origin(request: web.Request) -> bool:
    """Origin (else Referer) must name this request's Host; neither header, or an opaque `null` Origin, counts as cross-site."""
    source = request.headers.get("Origin") or request.headers.get("Referer") or ""
    return bool(source) and urlsplit(source).netloc == request.host


async def logout_post(request: web.Request) -> web.Response:
    """POST /logout (the project dashboard's Sign out form): same-origin only, so another site cannot force a sign-out."""
    if not same_origin(request):
        log.warning("web logout: refused cross-site POST (Origin=%r)", request.headers.get("Origin"))
        raise web.HTTPForbidden(text="cross-site logout refused")
    form = await request.post()
    return _end_session(request, str(form.get("next", "")))


def device_url(source: str, device_id: str) -> str:
    return "/dashboard/device/%s/%s" % (quote(str(source), safe=""), quote(str(device_id), safe=""))


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
        ["source", "device_id", "名字", "类型", "应在线", "最后入库", "距今", "状态"], cells, classes, "tbl-devices", cards=True,
        links={"名字": lambda i: device_url(rows[i]["source"], rows[i]["device_id"])})


def sensors_section(rows: List[Dict[str, Any]]) -> str:
    by_dev: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = by_dev.setdefault(r["device_id"], {"name": r["name"], "ts": r["ts"]})
        d[r["key"]] = r["value_si"] if r["value_si"] is not None else (r["value_num"] if r["value_num"] is not None else r["value_str"])
        if r["ts"] > d["ts"]:
            d["ts"] = r["ts"]
    cells = [[d["name"], dev, d.get("volt"), d.get("temperature"), d.get("rsrp"), fmt_ts(d["ts"])]
             for dev, d in sorted(by_dev.items(), key=lambda kv: str(kv[1]["name"]))]
    return "<h2>最新读数</h2>" + table(["名字", "device_id", "volt (V)", "temperature", "rsrp (dBm)", "时间"], cells, tbody_id="tbl-sensor", cards=True,
                                                                            links={"名字": lambda i: device_url("dingtek", cells[i][1])})


def gps_section(rows: List[Dict[str, Any]]) -> str:
    cells = [[r["name"], r["device_id"], fmt_ts(r["update_time"]), r["lat"], r["lon"], r["speed_kmh"], r["origin"]] for r in rows]
    return "<h2>最后位置</h2>" + table(["名字", "device_id", "时间", "lat", "lon", "speed_kmh", "origin"], cells, tbody_id="tbl-gps",
                                                                                    links={"名字": lambda i: device_url("gps51", cells[i][1])})


def paris_ts(at: datetime) -> str:
    return "%s 巴黎时间" % at.astimezone(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d %H:%M")


def collector_line(c: Dict[str, Any]) -> str:
    if c["updated_at"] is None:
        return "采集从未上报心跳"
    ws = "WS 未启用" if c["ws_connected"] is None else ("WS 已连" if c["ws_connected"] else "WS 未连")
    state = "%s · %s · v%s" % (ws, "轮询中" if c["polling"] else "推送", c["version"] or "?")
    if c["stale"]:  # SV-1: the old WS / polling values are not current facts once the heartbeat is stale
        return "采集心跳已过期，最后已知（%s）：%s" % (paris_ts(c["updated_at"]), state)
    return "采集心跳：%s（%d 秒前）· %s" % (paris_ts(c["updated_at"]), c["age_sec"], state)


RECEIVER_STALE_NOTE = "以下接收端计数为最后已知值（采集心跳已过期）"


def collector_section(ctx: Any, calls: List[Dict[str, Any]], now: datetime, receiver: Optional[Dict[str, Any]], collector: Dict[str, Any]) -> str:
    if receiver is None:
        rec = "<p>采集器尚未上报心跳</p>"
    else:
        pairs = [(k, receiver[k]) for k in ("received", "stored", "rejected", "unrecognised", "alarms", "failed", "queued")]
        pairs += [("silent", fmt_secs(receiver["silent_sec"])), ("message_silent", fmt_secs(receiver["message_silent_sec"]))]
        rec = table([k for k, _ in pairs], [[v for _, v in pairs]], tbody_id="tbl-receiver")
    api = table(["source", "action", "24h 调用数"], [[c["source"], c["action"], c["n"]] for c in calls], tbody_id="tbl-calls")
    info = '<p>Web 启动 %s · <span id="last-refresh">生成于 %s</span></p>' % (esc(fmt_ts(ctx.started_at)), esc(fmt_ts(now)))
    note = RECEIVER_STALE_NOTE if collector["stale"] and receiver is not None else ""
    return ("<h2>采集器状态</h2>" + '<p id="collector-line">' + esc(collector_line(collector)) + "</p>"
            + '<p id="receiver-note">' + esc(note) + "</p>" + rec + api + info)


def backup_line(summary: Dict[str, Any]) -> str:
    at: Optional[datetime] = summary["last_ok_at"]
    if at is None:
        return "上次备份：无"
    size = summary["last_ok_bytes"]
    return "上次备份：%s 巴黎时间 · %s" % (at.astimezone(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d %H:%M"),
                              "%.1f MB" % (size / 1048576) if size is not None else "-")


def anomalies_section(items: List[Dict[str, Any]]) -> str:
    head = "<h2>异常总览 · %s</h2>" % esc(anomalies.summarize(items))
    if not items:
        return head + '<p class="ok">全部正常</p>'
    lis = "".join('<li class="%s">[%s] %s · %s</li>' % (esc(i["level"]), esc(anomalies.KIND_LABELS.get(i["kind"], i["kind"])),
                                                       esc(i.get("name", "")), esc(i["detail"])) for i in items)
    return head + "<ul>%s</ul>" % lis


@require_admin
async def dashboard(request: web.Request) -> web.Response:
    ctx = request.app["ctx"]
    now = datetime.now(timezone.utc)
    status = await ctx.db.device_status()
    sensors = await ctx.db.latest_sensor_values(("volt", "temperature", "rsrp"))
    gps = await ctx.db.latest_gps_positions()
    calls = await ctx.db.call_summary(24)
    backup = await ctx.db.backup_summary()
    receiver, collector = heartbeat_view(await ctx.db.collector_status())
    items = await build_anomalies(ctx, now, status, sensors, calls, backup, receiver, collector)
    body = (ops_header(request["user"], ['<a href="/dashboard/map">地图</a>'])
            + '<h1>Lutetia 看板</h1><div id="anomalies">' + anomalies_section(items) + '</div><p id="last-backup">' + esc(backup_line(backup)) + '</p>' + devices_section(status, now)
            + sensors_section(sensors) + gps_section(gps) + collector_section(ctx, calls, now, receiver, collector))
    return page("Lutetia 看板", body, script=True)


def register_dashboard(app: web.Application) -> None:
    app.router.add_get("/", root)
    app.router.add_get("/login", login_get)
    app.router.add_post("/login", login_post)
    app.router.add_get("/logout", logout)
    app.router.add_post("/logout", logout_post)
    app.router.add_get("/dashboard/", dashboard)
