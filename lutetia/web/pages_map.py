"""Location map page: GPS last positions and manhole fixed points. The map and device list are drawn by /static/map.js."""
from aiohttp import web

from .auth import require_session
from .html import page


@require_session
async def map_page(request: web.Request) -> web.Response:
    days = "7" if request.query.get("tracks") == "1" else "0"
    body = ('<p><a href="/dashboard/">← 看板</a></p><h1>位置地图</h1>'
            '<p class="period"><a href="/dashboard/map?tracks=1">近 7 天轨迹</a> · <a href="/dashboard/map">只看最后位置</a></p>'
            '<div id="map-wrap"><div id="map" data-days="%s"></div><ul id="device-list"></ul></div>'
            '<p id="map-note"></p><p class="attribution">底图 © OpenStreetMap contributors</p>' % days)
    return page("位置地图", body, head='<link rel="stylesheet" href="/static/vendor/leaflet.css">',
                scripts='<script src="/static/vendor/leaflet.js" defer></script><script src="/static/map.js" defer></script>')


def register_map_pages(app: web.Application) -> None:
    app.router.add_get("/dashboard/map", map_page)
