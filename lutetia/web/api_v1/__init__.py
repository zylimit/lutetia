"""/api/v1: the one public, versioned, read-only data contract (ADR-5). v1 only adds, never changes."""
from aiohttp import web

from . import legacy, pois, resources


def register_api(app: web.Application) -> None:
    legacy.register_legacy(app)
    r = app.router
    r.add_get("/api/v1/summary", resources.summary)
    r.add_get("/api/v1/manholes", resources.manholes)
    r.add_get("/api/v1/fall-events", resources.fall_events)
    r.add_get("/api/v1/bundles", resources.bundles)
    r.add_get("/api/v1/bundles/{device_id}/track", resources.bundle_track)
    r.add_get("/api/v1/pois", pois.pois)
    r.add_get("/api/v1/pois/{poi_no}/segments", pois.poi_segments)
    r.add_get("/api/v1/collector-status", resources.collector_status)


__all__ = ["register_api"]
