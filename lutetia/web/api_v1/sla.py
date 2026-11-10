"""SLA process templates of /api/v1 (scope poi:read): reference only, never a per-order timeout (OUT-9). The tables are an Excel
snapshot like the POI ones: source "excel-snapshot", as_of = the newest imported_at (null when nothing was imported)."""
from aiohttp import web

from ... import queries_v1 as q
from ..auth import require_api
from .envelope import c_str, decode_cursor, errors_as_responses, list_response, parse_limit
from .pois import SOURCE


@require_api("poi:read")
@errors_as_responses
async def sla_templates(request: web.Request) -> web.Response:
    limit = parse_limit(request)
    after = decode_cursor(request, (c_str,))
    db = request.app["ctx"].db
    rows = await q.sla_templates(db, after[0] if after else None, limit + 1)
    page = rows[:limit]
    return list_response(page, await q.sla_snapshot_at(db), [page[-1]["template"]] if len(rows) > limit else None, SOURCE)
