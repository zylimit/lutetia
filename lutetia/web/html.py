"""Shared server-side HTML helpers for the dashboard pages (every dynamic value escaped)."""
import html
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from aiohttp import web


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


def page(title: str, body: str, script: bool = False, head: str = "", scripts: str = "") -> web.Response:
    js = '<script src="/static/app.js" defer></script>' if script else ""
    doc = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
           '<title>%s</title><link rel="stylesheet" href="/static/app.css">%s</head><body>%s%s%s</body></html>'
           % (esc(title), head, body, js, scripts))
    return web.Response(text=doc, content_type="text/html")


def ops_header(user: str, links: Optional[List[str]] = None) -> str:
    """Shared header of every ops page: nav links (trusted HTML), logout, and the escaped current account."""
    nav = "".join(l + " · " for l in (links or []))
    return ('<p id="ops-header"><span id="whoami" style="float:right">当前账号：<strong>%s</strong></span>%s<a href="/logout">退出</a></p>'
            % (esc(user), nav))


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
