"""Project dashboard single-page app under /app/: serves the web-ui build (Config.web_ui_dist) with history fallback.

Routing rules (Task 9.1):
- a real file inside the build directory is served as is;
- a path under /app/assets/ or whose last segment ends in a known static extension (STATIC_EXTENSIONS) and is not a real file -> 404, never index.html;
- any other path under /app/ (a front-end route such as /app/manholes, /app/pois/ABC.DEF) -> index.html;
- PWA files at the build root (sw.js, sw-signout.js, registerSW.js, workbox-*.js, manifest.webmanifest; Task 11.1) -> Cache-Control no-cache
  with an explicit Content-Type (the manifest as application/manifest+json); the worker's scope is /app/ only, never /embed/;
- build directory or its index.html missing (no `npm run build` locally, pure Python test env) -> 503 with a plain hint.
The strict CSP for /app and /app/* (SPA_CSP, no 'unsafe-inline') is stamped by app.security_headers via is_spa_path().
"""
import logging
import re
from pathlib import Path
from typing import Optional

from aiohttp import web

log = logging.getLogger(__name__)

SPA_PREFIX = "/app"
OSM_TILES = "https://tile.openstreetmap.org"
SPA_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: " + OSM_TILES + "; "
           "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
NOT_BUILT = "Project dashboard is not built on this server (web-ui build directory missing). Run `npm run build` in web-ui/."
INDEX_CACHE = "no-cache"
ASSET_CACHE = "public, max-age=31536000, immutable"  # Vite file names carry a content hash
# PWA files at the build root (Task 11.1): the browser must re-check them on every load, or a new build never reaches an
# installed phone. Content types are set here because Python 3.9 mimetypes does not know .webmanifest.
SW_CACHE = "no-cache"
MANIFEST = "manifest.webmanifest"
MANIFEST_TYPE = "application/manifest+json"
JS_TYPE = "text/javascript"
_PWA_SCRIPT = re.compile(r"(?:sw|sw-signout|registerSW|workbox-[0-9A-Za-z_-]+)\.js")
# A missing path ending in one of these is a missing file (404); any other dotted last segment (e.g. a POI id) is a front-end route
STATIC_EXTENSIONS = frozenset("js mjs css map woff woff2 ttf otf png jpg jpeg gif svg ico webp json webmanifest txt xml".split())


def is_spa_path(path: str) -> bool:
    return path == SPA_PREFIX or path.startswith(SPA_PREFIX + "/")


def _looks_like_file(tail: str) -> bool:
    last = tail.rsplit("/", 1)[-1]
    ext = last.rsplit(".", 1)[-1].lower() if "." in last else ""
    return tail.startswith("assets/") or ext in STATIC_EXTENSIONS


def _resolve_inside(root: Path, tail: str) -> Optional[Path]:
    """The real file for tail inside root, or None (missing, a directory, or escaping root via .. / symlink)."""
    if not tail:
        return None
    try:
        candidate = (root / tail).resolve()
        candidate.relative_to(root)
        # is_file() raises OSError(ENAMETOOLONG) on Python 3.9 / 3.12 for over-long names; a long name is just "not a file"
        return candidate if candidate.is_file() else None
    except (ValueError, OSError):
        return None


def _index_response(index: Path) -> web.FileResponse:
    resp = web.FileResponse(index)
    resp.headers["Cache-Control"] = INDEX_CACHE
    return resp


def make_handler(dist: Path):
    async def spa(request: web.Request) -> web.StreamResponse:
        try:
            root = dist.resolve()
        except OSError:
            root = dist
        index = root / "index.html"
        if not index.is_file():
            log.warning("GET %s: web-ui build not found at %s, answering 503", request.path, dist)
            return web.Response(status=503, text=NOT_BUILT)
        tail = request.match_info.get("tail", "")
        found = _resolve_inside(root, tail)
        if found is not None:
            if found == index:
                return _index_response(index)
            resp = web.FileResponse(found)
            if tail.startswith("assets/"):
                resp.headers["Cache-Control"] = ASSET_CACHE
            elif tail == MANIFEST:
                resp.headers["Content-Type"] = MANIFEST_TYPE
                resp.headers["Cache-Control"] = SW_CACHE
            elif _PWA_SCRIPT.fullmatch(tail):
                resp.headers["Content-Type"] = JS_TYPE
                resp.headers["Cache-Control"] = SW_CACHE
            return resp
        if _looks_like_file(tail):
            raise web.HTTPNotFound()
        return _index_response(index)
    return spa


def register_spa(app: web.Application, dist: Path) -> None:
    if not (dist / "index.html").is_file():
        log.warning("web-ui build not found at %s: /app/ answers 503 until it is built (WEB_UI_DIST)", dist)

    async def to_slash(request: web.Request) -> web.StreamResponse:
        raise web.HTTPFound(SPA_PREFIX + "/")

    app.router.add_get(SPA_PREFIX, to_slash)
    app.router.add_get(SPA_PREFIX + "/{tail:.*}", make_handler(dist))
