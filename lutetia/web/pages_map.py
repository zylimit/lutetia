"""Location map page: GPS last positions and manhole fixed points. The map and device list are drawn by /static/map.js."""
from aiohttp import web

from .auth import require_admin
from .html import esc, ops_header, page
from .i18n import pick_lang, t

OSM_ATTRIBUTION = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'


@require_admin
async def map_page(request: web.Request) -> web.Response:
    lang = pick_lang(request)
    days = "7" if request.query.get("tracks") == "1" else "0"
    title = t(lang, "map.title")
    body = (ops_header(request, request["user"], ['<a href="/dashboard/">%s</a>' % esc(t(lang, "nav.board"))]) + '<h1>%s</h1>' % esc(title)
            + '<p class="period"><a href="/dashboard/map?tracks=1">%s</a> · <a href="/dashboard/map">%s</a></p>'
            % (esc(t(lang, "map.tracks")), esc(t(lang, "map.last")))
            + '<div id="map-wrap"><div id="map" data-days="%s"></div><ul id="device-list"></ul></div>' % days
            + '<p id="map-note"></p><p class="attribution">%s %s</p>' % (esc(t(lang, "map.base")), OSM_ATTRIBUTION))
    return page(request, title, body, head='<link rel="stylesheet" href="/static/vendor/leaflet.css">',
                scripts='<script src="/static/vendor/leaflet.js" defer></script><script src="/static/map.js" defer></script>')


def register_map_pages(app: web.Application) -> None:
    app.router.add_get("/dashboard/map", map_page)
