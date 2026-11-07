# risk: high
"""Task 5.2：003_poi.sql 迁移 + lutetia.poi_store.apply_ledger 事务入库（真库集成，连不上 / 未设 DATABASE_URL 自动 skip）。

断言依据：派单书 brief-5.2 的接口约定与 Spec v1.8「数据与权限」poi / poi_cable_segment 两行、
SC-12 反向指标（失败整批回滚、消失的单标台账已无而不是删）。不 import 任何 xlsx 代码，PoiRecord / SegmentRecord
直接在 Python 里构造；工单号只用 6000xx 段（合成数据）。

安全：只在本机库（127.0.0.1 / localhost / ::1）上跑；只 truncate poi、poi_cable_segment 两张表；
表里若有不带 raw._test 标记的行（疑似真实台账）一律 skip，不清不写。
"""
import asyncio
import dataclasses
import hashlib
import json
import os
import re
from datetime import date
from decimal import Decimal
from importlib import resources
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import asyncpg
import pytest

from lutetia.db import Database
from lutetia.poi_import import PoiRecord, SegmentRecord

DB_URL = os.environ.get("DATABASE_URL", "")  # 故意不 load_dotenv：未显式给库就 skip，不被 .env 悄悄指到别的库
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
MARK = "poi_store"  # 本文件写入的行都在 raw._test 里带这个标记
KEYS = ["new", "updated", "unchanged", "raw_refreshed", "gone"]
POI_COLS_BIZ = ["uci", "subcon", "site_ville", "commune_code", "category", "status_raw", "occ_week_from",
                "occ_week_to", "occ_date_from", "occ_date_to", "received_date", "planned_op_date"]
SEG_COLS_BIZ = ["cable_category", "cable_type", "infra", "length_km", "weight_t", "ref_min_t", "ref_avg_t",
                "ref_max_t"]


# --------------------------------------------------------------------------- 夹具与构造器
@pytest.fixture
async def db():
    if not DB_URL:
        pytest.skip("DATABASE_URL not set")
    host = urlparse(DB_URL).hostname
    if host not in LOCAL_HOSTS:
        pytest.skip("refusing to run DDL / TRUNCATE on non-local database host: %s" % host)
    d = Database(DB_URL)
    try:
        await d.connect()
    except Exception as e:  # noqa: BLE001
        pytest.skip("database unreachable: %s" % e)
    try:
        yield d
    finally:
        await d.close()


def sql_003_text() -> str:
    return resources.files("lutetia").joinpath("sql/003_poi.sql").read_text(encoding="utf-8")


async def _truncate(pool) -> None:
    await pool.execute("TRUNCATE poi_cable_segment, poi")  # 只这两张表


@pytest.fixture
async def store(db):
    """建表（执行 003_poi.sql）、确认表里只有本文件的合成行、清空；返回连接池，用完再清。"""
    await db.pool.execute(sql_003_text())
    foreign = await db.pool.fetchval("SELECT count(*) FROM poi WHERE coalesce(raw->>'_test', '') <> $1", MARK)
    if foreign:
        pytest.skip("poi table holds %d rows not written by this test file; refusing to truncate" % foreign)
    await _truncate(db.pool)
    try:
        yield db.pool
    finally:
        await _truncate(db.pool)


def _sha(body: Any) -> str:
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=lambda o: o.isoformat())
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def finalize(p: PoiRecord) -> PoiRecord:
    """按「业务字段 + 有序段」算 content_sha、按「原文」算 raw_sha：改业务字段 content_sha 变，只改 raw 则只 raw_sha 变。"""
    biz = {f.name: getattr(p, f.name) for f in dataclasses.fields(PoiRecord)
           if f.name not in ("content_sha", "raw_sha", "raw", "segments")}
    biz["segments"] = [{f.name: getattr(s, f.name) for f in dataclasses.fields(SegmentRecord) if f.name != "raw"}
                       for s in p.segments]
    p.content_sha = _sha(biz)
    p.raw_sha = _sha({"raw": p.raw, "segments": [s.raw for s in p.segments]})
    return p


def seg(seq: int, **kw: Any) -> SegmentRecord:
    base = dict(cable_category="DECS2", cable_type="88-224-4", infra="sousterrain", length_km=0.5, weight_t=2.064,
                ref_min_t=1.9, ref_avg_t=2.057, ref_max_t=2.2,
                raw={"_test": MARK, "Cable": "88-224-4", "Weight(T)": 2.064 + seq})
    base.update(kw)
    return SegmentRecord(seq=seq, **base)


def mk(no: str, segments: Optional[List[SegmentRecord]] = None, **kw: Any) -> PoiRecord:
    base = dict(uci="AURA", subcon="SUB-X", site_ville="PARIS 15", commune_code="75115", category="DECS2",
                status_raw="OCC S48 - S49 2026/11/25 - 12/02", occ_week_from=48, occ_week_to=49,
                occ_date_from=date(2026, 11, 25), occ_date_to=date(2026, 12, 2), received_date=date(2026, 10, 1),
                planned_op_date=date(2026, 12, 15), raw={"_test": MARK, "POI": no, "Executed Weight": 0})
    base.update(kw)
    return finalize(PoiRecord(poi_no=no, segments=segments if segments is not None else [], **base))


def poi_a() -> PoiRecord:
    return mk("RNT600001", [seg(1, cable_type="88-224-4", weight_t=2.064), seg(2, cable_type="88-448-4", weight_t=3.5)])


def poi_b() -> PoiRecord:
    return mk("BRG600002", [seg(1, cable_type="22-100-2", weight_t=0.8)], uci="ORNG", subcon="SUB-Y")


def with_changes(p: PoiRecord, **kw: Any) -> PoiRecord:
    return finalize(dataclasses.replace(p, **kw))


def counts(**kw: int) -> Dict[str, int]:
    d = {k: 0 for k in KEYS}
    d.update(kw)
    return d


async def run(pool, pois: List[PoiRecord], dry_run: bool = False) -> Dict[str, int]:
    from lutetia.poi_store import apply_ledger  # 延迟 import：模块缺失时是逐用例失败，而不是整个文件收集期报错
    res = await apply_ledger(pool, pois, dry_run=dry_run)
    assert set(res) == set(KEYS), "返回键应恰为 %s，实际 %s" % (KEYS, sorted(res))
    assert res["new"] + res["updated"] + res["unchanged"] + res["raw_refreshed"] == len(pois), \
        "new+updated+unchanged+raw_refreshed 必须等于传入工单数: %s vs %d" % (res, len(pois))
    return res


async def snap(pool) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """两张表逐行逐列的完整快照（含 raw、时间戳），用来断言「回滚后与调用前逐行一致」。"""
    pois = [dict(r) for r in await pool.fetch("SELECT * FROM poi ORDER BY poi_no")]
    segs = [dict(r) for r in await pool.fetch("SELECT * FROM poi_cable_segment ORDER BY poi_no, seq")]
    return pois, segs


async def poi_row(pool, no: str) -> Optional[Dict[str, Any]]:
    r = await pool.fetchrow("SELECT * FROM poi WHERE poi_no = $1", no)
    return dict(r) if r else None


async def seg_rows(pool, no: str) -> List[Dict[str, Any]]:
    return [dict(r) for r in await pool.fetch("SELECT * FROM poi_cable_segment WHERE poi_no = $1 ORDER BY seq", no)]


def drop(d: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if k not in keys}


def num(v: Any) -> Optional[float]:
    return None if v is None else float(v)


async def count_rows(pool) -> Tuple[int, int]:
    return (await pool.fetchval("SELECT count(*) FROM poi"), await pool.fetchval("SELECT count(*) FROM poi_cable_segment"))


# --------------------------------------------------------------------------- 迁移 003_poi.sql（用例 9 + 表结构契约）
FIVE_TABLES = ["device", "gps_position", "sensor_telemetry", "sensor_attribute", "api_call"]
TWO_VIEWS = ["gps_position_v", "sensor_telemetry_v"]


async def _existing_shape(pool) -> Dict[str, int]:
    rows = await pool.fetch(
        "SELECT table_name, count(*) AS n FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = ANY($1::text[]) GROUP BY table_name", FIVE_TABLES + TWO_VIEWS)
    return {r["table_name"]: r["n"] for r in rows}


# risk: high
async def test_migration_003_is_idempotent_and_leaves_existing_objects_alone(db):
    sql = sql_003_text()
    before = await _existing_shape(db.pool)
    assert set(before) == set(FIVE_TABLES + TWO_VIEWS), "现有五张表两个视图应都在: %s" % sorted(before)
    await db.pool.execute(sql)
    await db.pool.execute(sql)  # 第二次执行不得报错
    await db.pool.execute(sql)
    assert await _existing_shape(db.pool) == before, "003 不得改动现有五张表与两个视图（名字与列数）"


# risk: high
def test_migration_003_static_guards():
    sql = re.sub(r"--[^\n]*", "", sql_003_text())
    assert not re.search(r"\b(drop|truncate)\b", sql, re.I), "003 不得 DROP / TRUNCATE 任何对象"
    creates = re.findall(r"create\s+(?:unique\s+)?(?:table|index)\b(?!\s+if\s+not\s+exists)", sql, re.I)
    assert creates == [], "每条 CREATE TABLE / INDEX 都要 IF NOT EXISTS: %s" % creates


# risk: high
async def test_migration_rerun_keeps_existing_poi_rows(store):
    """每次部署都会重跑迁移：重跑不能清掉已导入的台账。"""
    await run(store, [poi_a(), poi_b()])
    before = await snap(store)
    await store.execute(sql_003_text())
    assert await snap(store) == before


EXPECTED_POI_COLS = {
    "poi_no": "text", "uci": "text", "subcon": "text", "site_ville": "text", "commune_code": "text",
    "category": "text", "status_raw": "text", "occ_week_from": "integer", "occ_week_to": "integer",
    "occ_date_from": "date", "occ_date_to": "date", "received_date": "date", "planned_op_date": "date",
    "in_ledger": "boolean", "content_sha": "text", "raw_sha": "text", "raw": "jsonb",
    "first_imported_at": "timestamp with time zone", "imported_at": "timestamp with time zone",
}
EXPECTED_SEG_COLS = {
    "poi_no": "text", "seq": "integer", "cable_category": "text", "cable_type": "text", "infra": "text",
    "length_km": "numeric", "weight_t": "numeric", "ref_min_t": "numeric", "ref_avg_t": "numeric",
    "ref_max_t": "numeric", "raw": "jsonb",
}


# risk: high
@pytest.mark.parametrize("table,expected", [("poi", EXPECTED_POI_COLS), ("poi_cable_segment", EXPECTED_SEG_COLS)])
async def test_schema_has_contract_columns_and_types(store, table, expected):
    rows = await store.fetch(
        "SELECT column_name, data_type FROM information_schema.columns WHERE table_schema='public' AND table_name=$1",
        table)
    actual = {r["column_name"]: r["data_type"] for r in rows}
    missing = {c: t for c, t in expected.items() if c not in actual}
    wrong = {c: (t, actual[c]) for c, t in expected.items() if c in actual and actual[c] != t}
    assert missing == {} and wrong == {}, "缺列 %s；类型不符(期望, 实际) %s" % (missing, wrong)


# risk: high
async def test_schema_keys_defaults_and_indexes(store):
    # 最小插入：只给三个 NOT NULL 列，in_ledger 默认 true、两个时间戳默认 now()
    await store.execute("INSERT INTO poi (poi_no, content_sha, raw_sha) VALUES ('RNT600099', 'c', 'r')")
    r = await poi_row(store, "RNT600099")
    assert r["in_ledger"] is True
    assert r["first_imported_at"] is not None and r["imported_at"] is not None
    # 主键：poi_no 重复被拒
    with pytest.raises(asyncpg.UniqueViolationError):
        await store.execute("INSERT INTO poi (poi_no, content_sha, raw_sha) VALUES ('RNT600099', 'c', 'r')")
    # content_sha / raw_sha 不许空
    with pytest.raises(asyncpg.NotNullViolationError):
        await store.execute("INSERT INTO poi (poi_no, raw_sha) VALUES ('RNT600098', 'r')")
    with pytest.raises(asyncpg.NotNullViolationError):
        await store.execute("INSERT INTO poi (poi_no, content_sha) VALUES ('RNT600098', 'c')")
    # 段：外键指向 poi，复合主键 (poi_no, seq)
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await store.execute("INSERT INTO poi_cable_segment (poi_no, seq) VALUES ('RNT600097', 1)")
    await store.execute("INSERT INTO poi_cable_segment (poi_no, seq) VALUES ('RNT600099', 1)")
    with pytest.raises(asyncpg.UniqueViolationError):
        await store.execute("INSERT INTO poi_cable_segment (poi_no, seq) VALUES ('RNT600099', 1)")
    # ON DELETE CASCADE
    await store.execute("DELETE FROM poi WHERE poi_no = 'RNT600099'")
    assert await seg_rows(store, "RNT600099") == []
    # 三个索引
    defs = " ".join(r["indexdef"] for r in await store.fetch(
        "SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND tablename='poi'"))
    for col in ("uci", "subcon", "occ_week_from"):
        assert "(%s)" % col in defs, "poi 缺 %s 上的索引" % col


# --------------------------------------------------------------------------- apply_ledger：用例 1、2、3、4、5
# risk: high
async def test_first_import_new_two_pois_three_segments(store):
    res = await run(store, [poi_a(), poi_b()])
    assert res == counts(new=2)
    assert await count_rows(store) == (2, 3)
    segs = await store.fetch("SELECT poi_no, seq FROM poi_cable_segment ORDER BY poi_no, seq")
    assert [(r["poi_no"], r["seq"]) for r in segs] == [("BRG600002", 1), ("RNT600001", 1), ("RNT600001", 2)]
    for no in ("RNT600001", "BRG600002"):
        r = await poi_row(store, no)
        assert r["in_ledger"] is True
        assert r["first_imported_at"] is not None and r["imported_at"] is not None


# risk: high
async def test_every_column_roundtrips_to_the_right_place(store):
    """所有列取值互不相同：参数位次错位、字段串列都会在这里暴露。"""
    p = mk("RNT600003", [
        seg(1, cable_category="DECS2", cable_type="88-224-4", infra="sousterrain", length_km=1.25, weight_t=2.064,
            ref_min_t=1.1, ref_avg_t=2.057, ref_max_t=3.3),
        seg(2, cable_category="DECS3", cable_type="88-448-4", infra="aerien", length_km=None, weight_t=None,
            ref_min_t=None, ref_avg_t=None, ref_max_t=None),  # #N/A 置空：必须是 NULL，不是 0
    ], uci="AURA", subcon="SUB-Q", site_ville="LYON 3", commune_code="69383", category="DECS9",
        status_raw="Completed", occ_week_from=7, occ_week_to=9, occ_date_from=date(2026, 2, 16),
        occ_date_to=date(2026, 3, 1), received_date=date(2026, 1, 5), planned_op_date=date(2026, 4, 6))
    assert await run(store, [p]) == counts(new=1)
    r = await poi_row(store, "RNT600003")
    for col in POI_COLS_BIZ:
        assert r[col] == getattr(p, col), "poi.%s 存取不一致: %r vs %r" % (col, r[col], getattr(p, col))
    assert r["content_sha"] == p.content_sha and r["raw_sha"] == p.raw_sha
    assert r["raw"] == p.raw
    s1, s2 = await seg_rows(store, "RNT600003")
    for stored, want in ((s1, p.segments[0]), (s2, p.segments[1])):
        assert stored["seq"] == want.seq
        for col in SEG_COLS_BIZ:
            got, exp = stored[col], getattr(want, col)
            if col.endswith(("_km", "_t")):
                got, exp = num(got), num(exp)
            assert got == exp, "segment.%s 存取不一致: %r vs %r" % (col, got, exp)
        assert stored["raw"] == want.raw
    assert all(s2[c] is None for c in ("length_km", "weight_t", "ref_min_t", "ref_avg_t", "ref_max_t"))


# risk: medium
async def test_numeric_columns_store_clean_decimals_not_float_noise(store):
    """float 直接喂 numeric 会存成 2.06400000000000005684...；吨数汇总与展示要的是 2.064。"""
    await run(store, [mk("RNT600004", [seg(1, length_km=0.1, weight_t=2.064, ref_min_t=1.9, ref_avg_t=2.057,
                                          ref_max_t=2.2)])])
    s = (await seg_rows(store, "RNT600004"))[0]
    assert s["weight_t"] == Decimal("2.064")
    assert s["length_km"] == Decimal("0.1")
    assert s["ref_avg_t"] == Decimal("2.057")


# risk: high
async def test_reimport_same_ledger_is_unchanged_and_touches_nothing(store):
    await run(store, [poi_a(), poi_b()])
    before = await snap(store)
    await asyncio.sleep(0.05)  # 若误刷新 imported_at，必然看得出来
    res = await run(store, [poi_a(), poi_b()])
    assert res == counts(unchanged=2)
    assert await snap(store) == before, "原样再导：两张表（含 imported_at）必须逐行一致"


# risk: high
async def test_changed_segment_weight_is_updated_other_poi_untouched(store):
    await run(store, [poi_a(), poi_b()])
    a0, b0 = await poi_row(store, "RNT600001"), await poi_row(store, "BRG600002")
    b_segs0 = await seg_rows(store, "BRG600002")
    a_new = poi_a()
    a_new.segments[1].weight_t = 9.75  # 第 2 段重量变
    finalize(a_new)
    assert a_new.content_sha != a0["content_sha"]  # 测试自检：夹具确实让 content_sha 变了
    await asyncio.sleep(0.05)
    res = await run(store, [a_new, poi_b()])
    assert res == counts(updated=1, unchanged=1)
    segs = await seg_rows(store, "RNT600001")
    assert [s["seq"] for s in segs] == [1, 2], "仍是 2 段"
    assert num(segs[1]["weight_t"]) == 9.75 and num(segs[0]["weight_t"]) == 2.064
    a1 = await poi_row(store, "RNT600001")
    assert a1["content_sha"] == a_new.content_sha and a1["in_ledger"] is True
    assert a1["first_imported_at"] == a0["first_imported_at"], "更新不得重置首次导入时间"
    assert a1["imported_at"] > a0["imported_at"], "更新要刷新 imported_at"
    assert await poi_row(store, "BRG600002") == b0 and await seg_rows(store, "BRG600002") == b_segs0


# risk: high
@pytest.mark.parametrize("new_seq_count", [0, 1, 3])
async def test_updated_poi_replaces_segment_set_not_merges(store, new_seq_count):
    """段数变少 / 变多 / 清零：旧段必须删净（只按 seq upsert 会残留第 2 段）。"""
    await run(store, [poi_a()])
    a = poi_a()
    a.segments = [seg(i + 1, cable_type="NEW-%d" % (i + 1), weight_t=7.0 + i) for i in range(new_seq_count)]
    finalize(a)
    assert await run(store, [a]) == counts(updated=1)
    segs = await seg_rows(store, "RNT600001")
    assert [s["seq"] for s in segs] == list(range(1, new_seq_count + 1))
    assert [s["cable_type"] for s in segs] == ["NEW-%d" % (i + 1) for i in range(new_seq_count)]
    assert (await count_rows(store))[1] == new_seq_count


# risk: high
async def test_raw_only_change_is_raw_refreshed_not_updated(store):
    await run(store, [poi_a(), poi_b()])
    a0 = await poi_row(store, "RNT600001")
    a_segs0 = await seg_rows(store, "RNT600001")
    b0, b_segs0 = await poi_row(store, "BRG600002"), await seg_rows(store, "BRG600002")
    a_new = poi_a()
    a_new.raw = {"_test": MARK, "POI": "RNT600001", "Executed Weight": 1.5}  # 未映射列变了
    a_new.segments[0].raw = {"_test": MARK, "Cable": "88-224-4", "Executed": "yes"}
    finalize(a_new)
    assert a_new.content_sha == a0["content_sha"] and a_new.raw_sha != a0["raw_sha"]  # 测试自检
    await asyncio.sleep(0.05)
    res = await run(store, [a_new, poi_b()])
    assert res == counts(raw_refreshed=1, unchanged=1), "只 raw_sha 变：计 raw_refreshed，不计 updated"
    a1, a_segs1 = await poi_row(store, "RNT600001"), await seg_rows(store, "RNT600001")
    assert a1["raw"] == a_new.raw and a1["raw_sha"] == a_new.raw_sha
    assert a_segs1[0]["raw"] == a_new.segments[0].raw and a_segs1[1]["raw"] == a_new.segments[1].raw
    assert drop(a1, "raw", "raw_sha", "imported_at") == drop(a0, "raw", "raw_sha", "imported_at"), "业务字段不动"
    assert [drop(s, "raw") for s in a_segs1] == [drop(s, "raw") for s in a_segs0], "段的业务列不动、段数不变"
    assert a1["first_imported_at"] == a0["first_imported_at"]
    assert a1["imported_at"] > a0["imported_at"], "raw 刷新要刷新 imported_at"
    assert await poi_row(store, "BRG600002") == b0 and await seg_rows(store, "BRG600002") == b_segs0


# risk: high
async def test_content_and_raw_both_changed_counts_as_updated(store):
    """content_sha 变优先：同时 raw_sha 也变，仍是 updated 而不是 raw_refreshed。"""
    await run(store, [poi_a()])
    a = poi_a()
    a.uci = "OTHER"
    a.raw = {"_test": MARK, "POI": "RNT600001", "Executed Weight": 99}
    finalize(a)
    assert await run(store, [a]) == counts(updated=1)
    r = await poi_row(store, "RNT600001")
    assert r["uci"] == "OTHER" and r["raw"] == a.raw


# risk: high
async def test_poi_missing_from_file_is_marked_gone_not_deleted_then_returns(store):
    await run(store, [poi_a(), poi_b()])
    b0, b_segs0 = await poi_row(store, "BRG600002"), await seg_rows(store, "BRG600002")
    # 本次文件只有 A
    assert await run(store, [poi_a()]) == counts(unchanged=1, gone=1)
    b1 = await poi_row(store, "BRG600002")
    assert b1 is not None and b1["in_ledger"] is False, "台账已无：标 in_ledger=false，行不删"
    assert drop(b1, "in_ledger", "imported_at") == drop(b0, "in_ledger", "imported_at"), "其余列不动"
    assert await seg_rows(store, "BRG600002") == b_segs0, "段也不删"
    assert (await poi_row(store, "RNT600001"))["in_ledger"] is True
    # 再导同一份：已是 false 的不重复计
    assert await run(store, [poi_a()]) == counts(unchanged=1, gone=0)
    assert (await poi_row(store, "BRG600002"))["in_ledger"] is False
    # B 回到台账（内容与消失前完全相同）：算 updated，in_ledger 回 true
    assert await run(store, [poi_a(), poi_b()]) == counts(updated=1, unchanged=1)
    b2 = await poi_row(store, "BRG600002")
    assert b2["in_ledger"] is True
    assert b2["first_imported_at"] == b0["first_imported_at"]
    assert await seg_rows(store, "BRG600002") == b_segs0


# risk: high
async def test_gone_poi_returning_with_only_raw_changed_is_updated(store):
    """in_ledger=false 的单回来，哪怕只有 raw_sha 变也是 updated（不是 raw_refreshed），in_ledger 必须回 true。"""
    await run(store, [poi_a(), poi_b()])
    await run(store, [poi_a()])  # B 消失
    b = poi_b()
    b.raw = {"_test": MARK, "POI": "BRG600002", "Executed Weight": 3}
    finalize(b)
    assert await run(store, [poi_a(), b]) == counts(updated=1, unchanged=1)
    r = await poi_row(store, "BRG600002")
    assert r["in_ledger"] is True and r["raw"] == b.raw


# risk: high
async def test_all_pois_gone_in_one_import_counts_each_once(store):
    await run(store, [poi_a(), poi_b()])
    other = mk("CHT600003", [seg(1)])
    assert await run(store, [other]) == counts(new=1, gone=2)
    assert await count_rows(store) == (3, 4)
    flags = {r["poi_no"]: r["in_ledger"] for r in await store.fetch("SELECT poi_no, in_ledger FROM poi")}
    assert flags == {"RNT600001": False, "BRG600002": False, "CHT600003": True}


# --------------------------------------------------------------------------- 用例 6：毒行整批回滚
async def _assert_poison_rolls_back(pool, batch: List[PoiRecord]) -> None:
    before = await snap(pool)
    with pytest.raises(Exception) as ei:
        await run(pool, batch)
    assert not isinstance(ei.value, (ImportError, AttributeError, TypeError, NameError, AssertionError)), \
        "抛出的应是入库期异常而不是实现 / 调用笔误: %r" % ei.value
    assert await snap(pool) == before, "整批回滚：两张表必须与调用前逐行逐列一致"


# risk: high
async def test_poison_new_poi_rolls_back_whole_batch(store):
    await run(store, [poi_a()])  # 先放一个正常工单（同时是「实现已存在」的正向对照）
    good_new = mk("CHT600003", [seg(1)])
    poison = mk("CHT600004", [seg(1), seg(1, cable_type="DUP")])  # 同一工单两个 seq=1：主键冲突
    await _assert_poison_rolls_back(store, [poi_a(), good_new, poison])
    assert await poi_row(store, "CHT600003") is None, "毒行之前已写的新工单也要回滚"
    assert await count_rows(store) == (1, 2)


# risk: high
async def test_poison_on_updated_poi_keeps_old_segments_and_does_not_mark_gone(store):
    """更新路径是先删旧段再插新段：中途炸了，旧段必须还在；本次文件里没有的 B 也不能被标 gone。"""
    await run(store, [poi_a(), poi_b()])
    a_poison = poi_a()
    a_poison.segments = [seg(1, weight_t=5.0), seg(1, weight_t=6.0)]
    finalize(a_poison)
    await _assert_poison_rolls_back(store, [a_poison])
    assert [s["seq"] for s in await seg_rows(store, "RNT600001")] == [1, 2]
    assert (await poi_row(store, "BRG600002"))["in_ledger"] is True


# risk: high
async def test_poison_after_raw_refresh_and_updates_rolls_back_all(store):
    await run(store, [poi_a(), poi_b(), mk("CHT600003", [seg(1)])])
    a_changed = poi_a()
    a_changed.uci = "CHANGED"
    finalize(a_changed)
    b_raw = poi_b()
    b_raw.raw = {"_test": MARK, "POI": "BRG600002", "Executed Weight": 7}
    finalize(b_raw)
    poison = mk("CHT600005", [seg(1), seg(1)])
    await _assert_poison_rolls_back(store, [a_changed, b_raw, poison])  # CHT600003 缺席 -> 本该 gone，同样回滚


# --------------------------------------------------------------------------- 用例 7：dry_run
# risk: high
async def test_dry_run_on_empty_db_returns_counts_and_writes_nothing(store):
    res = await run(store, [poi_a(), poi_b()], dry_run=True)
    assert res == counts(new=2)
    assert await count_rows(store) == (0, 0)


# risk: high
async def test_dry_run_with_existing_data_matches_real_run_and_changes_nothing(store):
    d = mk("CHT600003", [seg(1)])
    await run(store, [poi_a(), poi_b(), d])
    before = await snap(store)
    a_upd = poi_a()
    a_upd.segments[0].weight_t = 4.4
    finalize(a_upd)
    d_raw = mk("CHT600003", [seg(1)], raw={"_test": MARK, "POI": "CHT600003", "Executed Weight": 8})
    c_new = mk("CHT600004", [seg(1), seg(2)])
    batch = lambda: [with_changes(a_upd), c_new, d_raw]  # noqa: E731  (B 缺席 -> gone)
    expect = counts(new=1, updated=1, raw_refreshed=1, gone=1)
    assert await run(store, batch(), dry_run=True) == expect
    assert await snap(store) == before, "dry-run 之后两张表与调用前逐行一致"
    assert await run(store, batch()) == expect, "dry-run 报的数字必须与真跑一致"
    assert await snap(store) != before


# --------------------------------------------------------------------------- 用例 8、11 与边界
# risk: high
async def test_poi_without_segments_is_stored_with_zero_segment_rows(store):
    bare = mk("RNT600005", [], uci=None, subcon=None, site_ville=None, commune_code=None, category=None,
              status_raw=None, occ_week_from=None, occ_week_to=None, occ_date_from=None, occ_date_to=None,
              received_date=None, planned_op_date=None, raw={"_test": MARK})
    assert await run(store, [bare, poi_a()]) == counts(new=2)
    assert await count_rows(store) == (2, 2)
    assert await seg_rows(store, "RNT600005") == []
    r = await poi_row(store, "RNT600005")
    assert all(r[c] is None for c in POI_COLS_BIZ), "None 存成 NULL"
    assert await run(store, [bare, poi_a()]) == counts(unchanged=2)


# risk: high
async def test_raw_with_chinese_quotes_newlines_roundtrips_exactly_as_jsonb_object(store):
    weird = {"_test": MARK, "Subcon": "法国电信 Société « Générale »", "note": 'He said "hi"\nline2\ttab \\ back/slash',
             "emoji": "🙂", "n": 2.064, "none": None, "nested": [1, None, {"é": "中文"}], "empty": ""}
    seg_raw = {"_test": MARK, "备注": "第二行\n\"引号\" 'single' \\", "x": [1.5, "a"]}
    p = mk("RNT600006", [seg(1, raw=seg_raw)], raw=weird)
    await run(store, [p])
    r = await poi_row(store, "RNT600006")
    assert r["raw"] == weird, "poi.raw 逐字相同"
    assert (await seg_rows(store, "RNT600006"))[0]["raw"] == seg_raw, "段 raw 逐字相同"
    # 服务端视角：必须是 jsonb 对象，不是被二次编码的字符串（同款坑见 002_raw_jsonb_fix.sql）
    typ = await store.fetchval("SELECT jsonb_typeof(raw) FROM poi WHERE poi_no = 'RNT600006'")
    styp = await store.fetchval("SELECT jsonb_typeof(raw) FROM poi_cable_segment WHERE poi_no = 'RNT600006'")
    assert (typ, styp) == ("object", "object")
    assert await store.fetchval("SELECT raw->>'note' FROM poi WHERE poi_no = 'RNT600006'") == weird["note"]


# risk: high
async def test_sql_metacharacters_in_text_fields_are_stored_as_data(store):
    evil = "x'); DROP TABLE poi_cable_segment; --"
    p = mk("RNT6000'1", [seg(1, cable_type=evil, infra="'; DELETE FROM poi; --")], uci=evil, subcon="a\\b%_'")
    assert await run(store, [poi_a(), p]) == counts(new=2)
    r = await poi_row(store, "RNT6000'1")
    assert r["uci"] == evil and r["subcon"] == "a\\b%_'"
    assert (await seg_rows(store, "RNT6000'1"))[0]["cable_type"] == evil
    assert await count_rows(store) == (2, 3), "表都还在、行都还在"
    assert await run(store, [poi_a(), p]) == counts(unchanged=2)


# risk: medium
async def test_batch_of_300_pois_counts_and_rows(store):
    pois = [mk("%s6000%02d" % (pre, n), [seg(1), seg(2)]) for pre in ("AAA", "AAB", "AAC") for n in range(100)]
    assert await run(store, pois) == counts(new=300)
    assert await count_rows(store) == (300, 600)
    assert await run(store, pois) == counts(unchanged=300)
    assert await run(store, pois[:100]) == counts(unchanged=100, gone=200)
    assert await store.fetchval("SELECT count(*) FROM poi WHERE in_ledger") == 100
    assert await count_rows(store) == (300, 600), "gone 不删行不删段"


# risk: high
async def test_empty_ledger_is_rejected_and_nothing_is_marked_gone(store):
    from lutetia.poi_store import apply_ledger
    assert await run(store, [poi_a()]) == counts(new=1)
    before = await snap(store)
    with pytest.raises(ValueError):
        await apply_ledger(store, [])
    assert await snap(store) == before, "空台账被拒后两张表须与调用前逐行一致"
    assert (await poi_row(store, "RNT600001"))["in_ledger"] is True


# risk: medium
async def test_duplicate_poi_no_in_one_batch_is_rejected_and_nothing_changes(store):
    from lutetia.poi_store import apply_ledger
    assert await run(store, [poi_b()]) == counts(new=1)
    before = await snap(store)
    with pytest.raises(ValueError):
        await apply_ledger(store, [poi_a(), poi_a()])
    assert await snap(store) == before
