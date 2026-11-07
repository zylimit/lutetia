"""POI 台账入库：一个事务内按两个指纹分流 new / updated / unchanged / raw_refreshed / gone。

失败整批回滚（异常向上抛）；dry_run 算完计数后同样回滚。台账里已无的工单只标 in_ledger=false，不删行不删段。
"""
import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

from .poi_import import PoiRecord, SegmentRecord

log = logging.getLogger(__name__)

POI_UPSERT = """
INSERT INTO poi (poi_no, uci, subcon, site_ville, commune_code, category, status_raw, occ_week_from, occ_week_to,
                 occ_date_from, occ_date_to, received_date, planned_op_date, in_ledger, content_sha, raw_sha, raw)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, true, $14, $15, $16)
ON CONFLICT (poi_no) DO UPDATE SET
    uci = EXCLUDED.uci, subcon = EXCLUDED.subcon, site_ville = EXCLUDED.site_ville,
    commune_code = EXCLUDED.commune_code, category = EXCLUDED.category, status_raw = EXCLUDED.status_raw,
    occ_week_from = EXCLUDED.occ_week_from, occ_week_to = EXCLUDED.occ_week_to,
    occ_date_from = EXCLUDED.occ_date_from, occ_date_to = EXCLUDED.occ_date_to,
    received_date = EXCLUDED.received_date, planned_op_date = EXCLUDED.planned_op_date,
    in_ledger = true, content_sha = EXCLUDED.content_sha, raw_sha = EXCLUDED.raw_sha, raw = EXCLUDED.raw,
    imported_at = now()
"""

SEG_INSERT = """
INSERT INTO poi_cable_segment (poi_no, seq, cable_category, cable_type, infra, length_km, weight_t,
                               ref_min_t, ref_avg_t, ref_max_t, raw)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
"""


def _dec(v: Any) -> Optional[Decimal]:
    # float 直接喂 numeric 会存成 2.06400000000000005...；先转字符串再 Decimal
    return None if v is None else Decimal(str(v))


def _poi_args(p: PoiRecord) -> List[Any]:
    return [p.poi_no, p.uci, p.subcon, p.site_ville, p.commune_code, p.category, p.status_raw, p.occ_week_from,
            p.occ_week_to, p.occ_date_from, p.occ_date_to, p.received_date, p.planned_op_date,
            p.content_sha, p.raw_sha, p.raw]


def _seg_args(poi_no: str, s: SegmentRecord) -> List[Any]:
    return [poi_no, s.seq, s.cable_category, s.cable_type, s.infra, _dec(s.length_km), _dec(s.weight_t),
            _dec(s.ref_min_t), _dec(s.ref_avg_t), _dec(s.ref_max_t), s.raw]


async def _write_poi(conn: Any, p: PoiRecord) -> None:
    """upsert 工单行（保留 first_imported_at），删旧段重插新段。"""
    await conn.execute(POI_UPSERT, *_poi_args(p))
    await conn.execute("DELETE FROM poi_cable_segment WHERE poi_no = $1", p.poi_no)
    if p.segments:
        await conn.executemany(SEG_INSERT, [_seg_args(p.poi_no, s) for s in p.segments])


async def _refresh_raw(conn: Any, p: PoiRecord) -> None:
    await conn.execute("UPDATE poi SET raw = $2, raw_sha = $3, imported_at = now() WHERE poi_no = $1",
                       p.poi_no, p.raw, p.raw_sha)
    if p.segments:
        await conn.executemany("UPDATE poi_cable_segment SET raw = $3 WHERE poi_no = $1 AND seq = $2",
                               [[p.poi_no, s.seq, s.raw] for s in p.segments])


async def _apply(conn: Any, pois: Sequence[PoiRecord]) -> Dict[str, int]:
    res = {"new": 0, "updated": 0, "unchanged": 0, "raw_refreshed": 0, "gone": 0}
    nos = [p.poi_no for p in pois]
    if not nos:
        raise ValueError("empty ledger: refusing to mark every POI gone")
    if len(set(nos)) != len(nos):
        raise ValueError("duplicate poi_no in one import batch")
    rows = await conn.fetch("SELECT poi_no, content_sha, raw_sha, in_ledger FROM poi WHERE poi_no = ANY($1::text[])",
                            nos)
    existing = {r["poi_no"]: r for r in rows}
    for p in pois:
        old = existing.get(p.poi_no)
        if old is None:
            await _write_poi(conn, p)
            res["new"] += 1
        elif old["content_sha"] != p.content_sha or not old["in_ledger"]:
            await _write_poi(conn, p)
            res["updated"] += 1
        elif old["raw_sha"] != p.raw_sha:
            await _refresh_raw(conn, p)
            res["raw_refreshed"] += 1
        else:
            res["unchanged"] += 1
    gone = await conn.fetch(
        "UPDATE poi SET in_ledger = false WHERE in_ledger AND poi_no <> ALL($1::text[]) RETURNING poi_no", nos)
    res["gone"] = len(gone)
    return res


async def apply_ledger(pool: Any, pois: Sequence[PoiRecord], dry_run: bool = False) -> Dict[str, int]:
    """一个事务内入库并返回五个计数；任何语句出错整批回滚并抛出；dry_run 算完即回滚。"""
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            res = await _apply(conn, pois)
        except BaseException:
            await tr.rollback()
            raise
        if dry_run:
            await tr.rollback()
        else:
            await tr.commit()
    log.info("apply_ledger dry_run=%s %s", dry_run, res)
    return res
