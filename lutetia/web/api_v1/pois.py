"""POI resources of /api/v1 (scope poi:read). The poi tables are an Excel snapshot; Ariane is the authority (Decisions 2026-11-08),
so every response says so: source "excel-snapshot" and as_of = the newest imported_at (rows only get a new imported_at when
their content changed, so this is the last import that changed something)."""
from datetime import date, datetime
from typing import Any, Dict

from aiohttp import web

from ... import queries_v1 as q
from ...db import Database
from ..auth import require_api
from .envelope import (BadParam, NotFound, c_int32, c_str, decode_cursor, errors_as_responses, list_response, no_nul,
                       parse_limit)

SOURCE = "excel-snapshot"
TEXT_FILTERS = ("uci", "subcontractor", "commune", "category", "network", "cable_type")  # network = segment infra (sousterrain / aerien)
DATE_FIELDS = ("occ_date_from", "occ_date_to", "received_date", "planned_op_date")


async def poi_summary_block(db: Database) -> Dict[str, Any]:
    r = await q.poi_summary(db)
    return {"count": r["count"], "with_segments": r["with_segments"], "planned_tonnes": r["planned_tonnes"],
            "without_weight": r["without_weight"]}


def _filters(request: web.Request) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name in TEXT_FILTERS:
        v = request.query.get(name)
        if v is None or v == "":
            continue
        if len(v) > 128:
            raise BadParam("%s is too long" % name)
        out[name] = no_nul(name, v)
    # work orders gone from the ledger are listed only on request, so the list agrees with the summary, which counts the ledger only (SC-10)
    flag = request.query.get("include_removed")
    if flag not in (None, "") and flag != "true":
        raise BadParam("include_removed must be true")
    if flag != "true":
        out["in_ledger"] = True
    return out


def _poi_item(r: Dict[str, Any]) -> Dict[str, Any]:
    # numerics are Decimal (jsonutil writes numbers); planned_tonnes stays null when no segment has a weight: weight pending, never 0
    return {k: (v.isoformat() if isinstance(v, date) and not isinstance(v, datetime) else v) for k, v in r.items()}


@require_api("poi:read")
@errors_as_responses
async def pois(request: web.Request) -> web.Response:
    limit = parse_limit(request)
    filters = _filters(request)
    after = decode_cursor(request, (c_str,))
    db = request.app["ctx"].db
    rows = await q.poi_page(db, filters, after[0] if after else None, limit + 1)
    page = rows[:limit]
    return list_response([_poi_item(r) for r in page], await q.poi_snapshot_at(db),
                         [page[-1]["poi_no"]] if len(rows) > limit else None, SOURCE)


@require_api("poi:read")
@errors_as_responses
async def poi_segments(request: web.Request) -> web.Response:
    poi_no = no_nul("poi_no", request.match_info["poi_no"])
    limit = parse_limit(request)
    after = decode_cursor(request, (c_int32,))
    db = request.app["ctx"].db
    exists, imported_at = await q.poi_imported_at(db, poi_no)
    if not exists:
        raise NotFound("unknown poi")
    rows = await q.poi_segments(db, poi_no, after[0] if after else None, limit + 1)
    page = rows[:limit]
    return list_response(page, imported_at, [page[-1]["seq"]] if len(rows) > limit else None, SOURCE)
