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
from .i18n import pick_lang, t

log = logging.getLogger(__name__)

def fmt_secs(sec: float, lang: str = "en") -> str:
    return fmt_ago(datetime.now(timezone.utc) - timedelta(seconds=sec), datetime.now(timezone.utc), lang)


def login_page(request: web.Request, message: str = "", next_url: str = "", status: int = 200) -> web.Response:
    lang = pick_lang(request)
    msg = "<p>%s</p>" % esc(message) if message else ""
    body = ('<h1>%s</h1>%s<form method="post" action="/login">'
            '<input type="hidden" name="next" value="%s">'
            '<p><label>%s <input name="username" autofocus autocapitalize="none" autocorrect="off" spellcheck="false" autocomplete="username"></label></p>'
            '<p><label>%s <input name="password" type="password" autocomplete="current-password"></label></p>'
            '<p><label><input name="remember" type="checkbox" value="1"> %s</label></p>'
            '<p><button type="submit">%s</button></p></form>'
            % (esc(t(lang, "login.title")), msg, esc(next_url), esc(t(lang, "login.user")), esc(t(lang, "login.password")),
               esc(t(lang, "login.remember")), esc(t(lang, "login.submit"))))
    resp = page(request, t(lang, "login.title"), body)
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
    return login_page(request, next_url=safe_next(request.query.get("next", "")))


async def login_post(request: web.Request) -> web.Response:
    ctx = request.app["ctx"]
    ip = client_ip(request, ctx.cfg.trust_proxy)
    form = await request.post()
    next_url, from_spa = resolve_next(str(form.get("next", "")))
    if ctx.limiter.is_globally_locked() or ctx.limiter.is_locked(ip):
        log.warning("web login: ip %s locked", ip)
        if from_spa:
            raise web.HTTPSeeOther(spa_signin_url("locked", next_url))
        return login_page(request, t(pick_lang(request), "login.locked"), next_url, 429)
    user = authenticate(ctx.cfg.accounts(), str(form.get("username", "")), str(form.get("password", "")))
    if user is None:
        ctx.limiter.record_failure(ip)
        log.warning("web login: failed attempt from %s", ip)
        if from_spa:
            raise web.HTTPSeeOther(spa_signin_url("1", next_url))
        return login_page(request, t(pick_lang(request), "login.wrong"), next_url, 401)
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


def yes_no(value: Any, lang: str) -> str:
    return {True: t(lang, "yes"), False: t(lang, "no")}.get(value, "?")


def devices_section(rows: List[Dict[str, Any]], now: datetime, lang: str = "en") -> str:
    cells, classes = [], []
    for r in rows:
        last = r["last_ts"]
        limit = max_age_hours(3.0, r["upload_interval_h"])
        stale = bool(r["expected_online"]) and (last is None or now - last > timedelta(hours=limit))
        cells.append([r["source"], r["device_id"], r["name"], r["device_type"], yes_no(r["expected_online"], lang),
                      fmt_ts(last), fmt_ago(last, now, lang), t(lang, "state.stale") if stale else ""])
        classes.append("stale" if stale else "")
    name = t(lang, "col.name")
    return "<h2>%s</h2>" % esc(t(lang, "sec.devices")) + table(
        ["source", "device_id", name, t(lang, "col.type"), t(lang, "col.online"), t(lang, "col.last"), t(lang, "col.age"),
         t(lang, "col.status")], cells, classes, "tbl-devices", cards=True,
        links={name: lambda i: device_url(rows[i]["source"], rows[i]["device_id"])})


def sensors_section(rows: List[Dict[str, Any]], lang: str = "en") -> str:
    by_dev: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = by_dev.setdefault(r["device_id"], {"name": r["name"], "ts": r["ts"]})
        d[r["key"]] = r["value_si"] if r["value_si"] is not None else (r["value_num"] if r["value_num"] is not None else r["value_str"])
        if r["ts"] > d["ts"]:
            d["ts"] = r["ts"]
    cells = [[d["name"], dev, d.get("volt"), d.get("temperature"), d.get("rsrp"), fmt_ts(d["ts"])]
             for dev, d in sorted(by_dev.items(), key=lambda kv: str(kv[1]["name"]))]
    name = t(lang, "col.name")
    return "<h2>%s</h2>" % esc(t(lang, "sec.sensors")) + table(
        [name, "device_id", "volt (V)", "temperature", "rsrp (dBm)", t(lang, "col.time")], cells, tbody_id="tbl-sensor", cards=True,
        links={name: lambda i: device_url("dingtek", cells[i][1])})


def gps_section(rows: List[Dict[str, Any]], lang: str = "en") -> str:
    cells = [[r["name"], r["device_id"], fmt_ts(r["update_time"]), r["lat"], r["lon"], r["speed_kmh"], r["origin"]] for r in rows]
    name = t(lang, "col.name")
    return "<h2>%s</h2>" % esc(t(lang, "sec.gps")) + table(
        [name, "device_id", t(lang, "col.time"), "lat", "lon", "speed_kmh", "origin"], cells, tbody_id="tbl-gps",
        links={name: lambda i: device_url("gps51", cells[i][1])})


def paris_ts(at: datetime, lang: str = "en") -> str:
    return t(lang, "time.paris", t=at.astimezone(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d %H:%M"))


def collector_line(c: Dict[str, Any], lang: str = "en") -> str:
    if c["updated_at"] is None:
        return t(lang, "cl.never")
    ws = t(lang, "cl.ws_off") if c["ws_connected"] is None else t(lang, "cl.ws_on" if c["ws_connected"] else "cl.ws_down")
    state = "%s · %s · v%s" % (ws, t(lang, "cl.polling" if c["polling"] else "cl.push"), c["version"] or "?")
    if c["stale"]:  # SV-1: the old WS / polling values are not current facts once the heartbeat is stale
        return t(lang, "cl.stale", at=paris_ts(c["updated_at"], lang), state=state)
    return t(lang, "cl.fresh", at=paris_ts(c["updated_at"], lang), age=int(c["age_sec"]), state=state)


def collector_section(ctx: Any, calls: List[Dict[str, Any]], now: datetime, receiver: Optional[Dict[str, Any]], collector: Dict[str, Any],
                      lang: str = "en") -> str:
    if receiver is None:
        rec = "<p>%s</p>" % esc(t(lang, "rec.none"))
    else:
        pairs = [(k, receiver[k]) for k in ("received", "stored", "rejected", "unrecognised", "alarms", "failed", "queued")]
        pairs += [("silent", fmt_secs(receiver["silent_sec"], lang)), ("message_silent", fmt_secs(receiver["message_silent_sec"], lang))]
        rec = table([k for k, _ in pairs], [[v for _, v in pairs]], tbody_id="tbl-receiver")
    api = table(["source", "action", t(lang, "col.calls")], [[c["source"], c["action"], c["n"]] for c in calls], tbody_id="tbl-calls")
    info = '<p>%s · <span id="last-refresh">%s</span></p>' % (esc(t(lang, "info.started", t=fmt_ts(ctx.started_at))),
                                                              esc(t(lang, "info.generated", t=fmt_ts(now))))
    note = t(lang, "rec.stale") if collector["stale"] and receiver is not None else ""
    return ("<h2>%s</h2>" % esc(t(lang, "sec.collector")) + '<p id="collector-line">' + esc(collector_line(collector, lang)) + "</p>"
            + '<p id="receiver-note">' + esc(note) + "</p>" + rec + api + info)


def backup_line(summary: Dict[str, Any], lang: str = "en") -> str:
    at: Optional[datetime] = summary["last_ok_at"]
    if at is None:
        return t(lang, "bk.none")
    size = summary["last_ok_bytes"]
    return t(lang, "bk.line", at=paris_ts(at, lang), size="%.1f MB" % (size / 1048576) if size is not None else "-")


def anomalies_section(items: List[Dict[str, Any]], lang: str = "en") -> str:
    head = "<h2>%s</h2>" % esc(t(lang, "anom.title", summary=anomalies.summarize(items, lang)))
    if not items:
        return head + '<p class="ok">%s</p>' % esc(t(lang, "anom.ok"))
    lis = "".join('<li class="%s">[%s] %s · %s</li>' % (esc(i["level"]), esc(t(lang, "kind." + i["kind"])),
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
    lang = pick_lang(request)
    items = await build_anomalies(ctx, now, status, sensors, calls, backup, receiver, collector, lang)
    title = t(lang, "dash.title")
    body = (ops_header(request, request["user"], ['<a href="/dashboard/map">%s</a>' % esc(t(lang, "nav.map"))])
            + '<h1>%s</h1><div id="anomalies">' % esc(title) + anomalies_section(items, lang) + '</div><p id="last-backup">'
            + esc(backup_line(backup, lang)) + '</p>' + devices_section(status, now, lang)
            + sensors_section(sensors, lang) + gps_section(gps, lang) + collector_section(ctx, calls, now, receiver, collector, lang))
    return page(request, title, body, script=True)


def register_dashboard(app: web.Application) -> None:
    app.router.add_get("/", root)
    app.router.add_get("/login", login_get)
    app.router.add_post("/login", login_post)
    app.router.add_get("/logout", logout)
    app.router.add_post("/logout", logout_post)
    app.router.add_get("/dashboard/", dashboard)
