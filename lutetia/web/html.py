"""Shared server-side HTML helpers for the dashboard pages (every dynamic value escaped)."""
import html
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlencode

from aiohttp import web

from .i18n import LANGS, pick_lang, t


def esc(v: Any) -> str:
    return html.escape("" if v is None else str(v))


def fmt_ts(ts: Optional[datetime]) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if ts else "-"


def fmt_ago(ts: Optional[datetime], now: datetime, lang: str = "en") -> str:
    if ts is None:
        return "-"
    minutes = max(0, int((now - ts).total_seconds() // 60))
    if minutes < 60:
        return t(lang, "ago.min", n=minutes)
    if minutes < 24 * 60:
        return t(lang, "ago.hour", n=minutes // 60)
    return t(lang, "ago.day", n=minutes // (24 * 60))


def page(request: web.Request, title: str, body: str, script: bool = False, head: str = "", scripts: str = "") -> web.Response:
    """Whole HTML document in the request's language. Pages with scripts first load the dictionary of that language (/i18n/<lang>.js)
    and the T() helper (/static/i18n.js); deferred scripts run in document order, so both are ready for app.js and the others."""
    lang = pick_lang(request)
    i18n_js = '<script src="/i18n/%s.js" defer></script><script src="/static/i18n.js" defer></script>' % lang if script or scripts else ""
    js = '<script src="/static/app.js" defer></script>' if script else ""
    doc = ('<!doctype html><html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
           '<title>%s</title><link rel="stylesheet" href="/static/app.css">%s</head><body>%s%s%s%s</body></html>'
           % (lang, esc(title), head, body, i18n_js, js, scripts))
    return web.Response(text=doc, content_type="text/html")


def ops_header(request: web.Request, user: str, links: Optional[List[str]] = None) -> str:
    """Shared header of every ops page: nav links (trusted HTML), logout, and the escaped current account."""
    lang = pick_lang(request)
    nav = "".join(l + " · " for l in (links or []))
    return ('<p id="ops-header"><span id="whoami" style="float:right">%s <strong>%s</strong></span>%s<a href="/logout">%s</a> · %s</p>'
            % (esc(t(lang, "hdr.account")), esc(user), nav, esc(t(lang, "hdr.logout")), lang_switch(request, lang)))


def lang_switch(request: web.Request, current: str) -> str:
    """EN / FR links to this same page (other query parameters kept, ?lang= replaced). The current language is not a link."""
    keep = [(k, v) for k, v in request.query.items() if k != "lang"]
    out = []
    for code in LANGS:
        if code == current:
            out.append('<span aria-current="true">%s</span>' % code.upper())
        else:
            href = "%s?%s" % (quote(request.path), urlencode(keep + [("lang", code)]))
            out.append('<a href="%s" hreflang="%s">%s</a>' % (esc(href), code, code.upper()))
    return " / ".join(out)


def table(headers: List[str], rows: List[List[Any]], row_class: Optional[List[str]] = None, tbody_id: str = "",
          cards: bool = False, links: Optional[Dict[str, Callable[[int], str]]] = None) -> str:
    """links maps a header to a function(row index) -> href; that column renders as an <a> with the escaped cell text."""
    out = [("<table class=\"cards\">" if cards else "<table>") + "<thead><tr>" + "".join("<th>%s</th>" % esc(h) for h in headers) + "</tr></thead>",
           '<tbody id="%s">' % esc(tbody_id) if tbody_id else "<tbody>"]
    for i, r in enumerate(rows):
        cls = ' class="%s"' % row_class[i] if row_class and row_class[i] else ""
        tds = []
        for j, c in enumerate(r):
            label = headers[j] if j < len(headers) else ""
            inner = esc(c)
            if links and label in links:
                inner = '<a href="%s">%s</a>' % (esc(links[label](i)), inner)
            tds.append('<td data-label="%s">%s</td>' % (esc(label), inner))
        out.append("<tr%s>" % cls + "".join(tds) + "</tr>")
    return "".join(out) + "</tbody></table>"
