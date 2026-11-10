"""/api/v1: the one public, versioned, read-only data contract (ADR-5). v1 only adds, never changes."""
from pathlib import Path

from aiohttp import web

from ..auth import require_api
from . import legacy, me, pois, resources, series, sla

OPENAPI_FILE = Path(__file__).resolve().parent.parent / "openapi.json"
OPENAPI_BYTES: "web.AppKey[bytes]" = web.AppKey("openapi_bytes", bytes)


@require_api(None)  # the contract itself: any valid key or session, whatever its scopes; one key lookup, in the guard
async def openapi_doc(request: web.Request) -> web.Response:
    return web.Response(body=request.app[OPENAPI_BYTES], content_type="application/json", charset="utf-8")


def register_api(app: web.Application) -> None:
    app[OPENAPI_BYTES] = OPENAPI_FILE.read_bytes()  # read once at startup: a missing file stops the server here, not at the first call
    legacy.register_legacy(app)
    r = app.router
    r.add_get("/api/v1/openapi.json", openapi_doc)
    r.add_get("/api/v1/me", me.me)
    r.add_get("/api/v1/summary", resources.summary)
    r.add_get("/api/v1/manholes", resources.manholes)
    r.add_get("/api/v1/fall-events", resources.fall_events)
    r.add_get("/api/v1/manholes/{device_id}/series", series.manhole_series)
    r.add_get("/api/v1/bundles", resources.bundles)
    r.add_get("/api/v1/bundles/{device_id}/track", resources.bundle_track)
    r.add_get("/api/v1/pois", pois.pois)
    r.add_get("/api/v1/pois/{poi_no}/segments", pois.poi_segments)
    r.add_get("/api/v1/sla-templates", sla.sla_templates)
    r.add_get("/api/v1/collector-status", resources.collector_status)


__all__ = ["register_api"]
