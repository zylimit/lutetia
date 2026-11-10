"""Embedded widgets under /embed/<name> (Phase 12, ADR-6, THR-2): the only pages another site may frame.

- Only the names in WIDGETS answer (embed.html of the web-ui build, Cache-Control no-store); any other /embed path is 404.
- A widget answer carries SPA_CSP with frame-ancestors set to the embed origins and no X-Frame-Options. The handler only marks the
  request (EMBED_CSP); app.security_headers writes the headers, so a 404 / 503 / error under /embed keeps frame-ancestors 'none' + DENY.
- Embed origins come from EMBED_FRAME_ANCESTORS only (Config.embed_frame_ancestors, default https://*.digifiber.net), not from the
  API caller registry: who may frame the widgets and who may call the API with a key are separate lists (Phase 12 review Q2).
  Each entry must be an exact origin that callers.origin_allowed accepts, or https://*.<name> where https://<name> is accepted, or
  the default pattern itself; anything else is left out with a warning. None left -> frame-ancestors stays 'none' (error logged).
  /api/v1/embed-config returns the same list, so the widget sends and accepts postMessage only for those origins.
- Assets of embed.html stay under /app/assets (one Vite build with base /app/); the service worker's scope is /app/ only, and
  embed.html never registers it.
"""
import logging
import re
from pathlib import Path
from typing import List

from aiohttp import web

from .callers import ORIGIN_SUFFIX, origin_allowed
from .spa import NOT_BUILT, SPA_CSP

log = logging.getLogger(__name__)

EMBED_PREFIX = "/embed"
WIDGETS = frozenset(("fall-timeline", "manhole-map", "security-summary"))
EMBED_FILE = "embed.html"
EMBED_CACHE = "no-store"
WILDCARD = "https://*."
DEFAULT_PATTERN = "https://*" + ORIGIN_SUFFIX
FRAME_NONE = "frame-ancestors 'none'"
EMBED_ORIGINS: "web.AppKey[List[str]]" = web.AppKey("embed_origins", list)
# Set by the widget handler; app.security_headers reads it. Holds the full CSP of that one response.
EMBED_CSP: "web.RequestKey[str]" = web.RequestKey("embed_csp", str)


def _entry_ok(entry: str) -> bool:
    if entry == DEFAULT_PATTERN:
        return True
    if entry.startswith(WILDCARD):
        return origin_allowed("https://" + entry[len(WILDCARD):])
    return origin_allowed(entry)


def parse_frame_ancestors(raw: str) -> List[str]:
    """EMBED_FRAME_ANCESTORS (ASCII spaces, tabs or commas between entries) -> the valid entries in order, without duplicates;
    [] = none valid. Any other whitespace (a newline, a no-break space) stays inside its entry, which then fails and is left out."""
    found: List[str] = []
    for entry in (x for x in re.split(r"[ \t,]+", raw.strip()) if x):
        if _entry_ok(entry):
            if entry not in found:
                found.append(entry)
        else:
            log.warning("EMBED_FRAME_ANCESTORS: entry %r is not https://<name>%s or https://*.<name>%s, left out",
                        re.sub(r"[^\x21-\x7e]", "?", entry)[:100], ORIGIN_SUFFIX, ORIGIN_SUFFIX)
    if not found:
        log.error("EMBED_FRAME_ANCESTORS has no valid entry: /embed/* keeps frame-ancestors 'none', no site can frame the widgets")
    return found


def embed_csp(origins: List[str]) -> str:
    if FRAME_NONE not in SPA_CSP:
        raise RuntimeError("SPA_CSP has no frame-ancestors 'none' to replace")
    return SPA_CSP.replace(FRAME_NONE, "frame-ancestors " + " ".join(origins)) if origins else SPA_CSP


def make_handler(dist: Path):
    async def widget(request: web.Request) -> web.StreamResponse:
        if request.match_info["name"] not in WIDGETS:
            raise web.HTTPNotFound()
        page = dist / EMBED_FILE
        if not page.is_file():
            log.warning("GET %s: %s not found in the web-ui build at %s, answering 503", request.path, EMBED_FILE, dist)
            return web.Response(status=503, text=NOT_BUILT)
        origins = request.app[EMBED_ORIGINS]
        if origins:  # none valid: the default stamp (frame-ancestors 'none' + DENY) stays
            request[EMBED_CSP] = embed_csp(origins)
        resp = web.FileResponse(page)
        resp.headers["Cache-Control"] = EMBED_CACHE
        return resp
    return widget


def register_embed(app: web.Application, dist: Path, frame_ancestors: str) -> None:
    app[EMBED_ORIGINS] = parse_frame_ancestors(frame_ancestors)  # once at startup: a bad entry is logged once, not per request
    app.router.add_get(EMBED_PREFIX + "/{name}", make_handler(dist))
