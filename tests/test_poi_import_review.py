# risk: high
"""lutetia.poi_import：代码审查后追加的规则（M-3 成段按原始格、M-4 续行不得带工单级字段与 POI 错误值、
M-5 双指纹 raw_sha、L-1 计划重量列位置、L-2 occ_unparsed 新口径、L-4 t="d" 格）。
断言来自派单书的规则条文，不看实现；fixture 全是合成值，工单号只用 6000xx 段。
旧用例仍在 tests/test_poi_import.py，这里只放这一轮新增的，不往旧文件里堆。"""
import dataclasses
import re

import pytest

from lutetia.poi_import import LedgerError, PoiRecord, parse_ledger
from xlsx_builder import COLS, HEADERS, Err, Formula, IsoDate, ledger_row, write_ledger

OCC_OK = "OCC S48 - S49 2026/11/25 - 12/02"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def parse(tmp_path, rows, headers=None, name="ledger.xlsx"):
    return parse_ledger(write_ledger(tmp_path / name, rows, headers=headers))


def by_no(res):
    return {p.poi_no: p for p in res.pois}


def order_rows(poi, cables, uci="AURA", status=OCC_OK):
    rows = []
    for i, (cable, w) in enumerate(cables):
        kw = dict(cable=cable, weight=w, ref_avg=w, length=1.0 + i, infra="Aerial", cable_category="Transport")
        if i == 0:
            kw.update(poi=poi, uci=uci, status=status, subcon="SUBCO A", site_ville="TESTVILLE",
                      commun="44000", category="Transport")
        rows.append(ledger_row(**kw))
    if not cables:
        rows.append(ledger_row(poi=poi, uci=uci, status=status, subcon="SUBCO A", site_ville="TESTVILLE"))
    return rows


def three_orders():
    return [order_rows("RNT600001", [("A-1", 1.0), ("B-2", 2.0)]),
            order_rows("RNT600002", [("C-3", 3.0)], uci="OUEST", status="OCC ?"),
            order_rows("RNT600003", [])]


def flat(groups):
    return [r for g in groups for r in g]


# ------------------------------------------------------------------ M-3 成段按原始格、转数字失败不让整行消失

# risk: high
def test_text_in_weight_cell_keeps_the_segment_with_null_weight(tmp_path):
    rows = [ledger_row(poi="RNT600001", uci="AURA", cable="88-224-4", weight=1.0),
            ledger_row(weight="n/a")]  # 续行：别的段字段全空，重量格是文本 "n/a"
    res = parse(tmp_path, rows)
    segs = res.pois[0].segments
    assert len(segs) == 2
    assert (segs[1].seq, segs[1].cable_type, segs[1].weight_t) == (2, None, None)
    assert res.segment_count == 2
    assert res.cleaned["not_a_number"] == 1
    assert res.cleaned["segment_no_cable_type"] == 1


# risk: high
@pytest.mark.parametrize("field,attr", [
    ("length", "length_km"), ("weight", "weight_t"), ("ref_min", "ref_min_t"),
    ("ref_avg", "ref_avg_t"), ("ref_max", "ref_max_t"),
])
def test_text_in_any_numeric_cell_becomes_none_and_counts_not_a_number(tmp_path, field, attr):
    kw = dict(poi="RNT600001", cable="88-224-4", length=1.0, weight=2.0, ref_min=1.0, ref_avg=1.5, ref_max=2.0)
    kw[field] = "n/a"
    res = parse(tmp_path, [ledger_row(**kw)])
    seg = res.pois[0].segments[0]
    assert getattr(seg, attr) is None
    assert res.cleaned["not_a_number"] == 1
    assert res.cleaned["na_to_empty"] == 0  # 文本 n/a 不是 Excel 的 #N/A 错误值，两个计数分开


# risk: medium
def test_error_value_in_numeric_cell_counts_as_na_not_as_not_a_number(tmp_path):
    res = parse(tmp_path, [ledger_row(poi="RNT600001", cable="88-224-4", weight=Err("#N/A"))])
    assert res.pois[0].segments[0].weight_t is None
    assert res.cleaned["na_to_empty"] == 1 and res.cleaned["not_a_number"] == 0


# ------------------------------------------------------------------ M-4 续行不得带工单级字段、POI 不得是错误值

# risk: high
@pytest.mark.parametrize("field,value", [
    ("subcon", "SUBCO A"), ("site_ville", "TESTVILLE"), ("commun", "44000"), ("status", "OCC ?"),
])
def test_continuation_row_carrying_a_poi_level_field_is_rejected(tmp_path, field, value):
    rows = [ledger_row(poi="RNT600001", uci="AURA", cable="88-224-4", weight=1.0),
            ledger_row(cable="88-448-4", weight=2.0, **{field: value})]
    with pytest.raises(LedgerError) as ei:
        parse(tmp_path, rows)
    assert re.search(r"row \d+: continuation row carries POI-level field", str(ei.value)), str(ei.value)


# risk: high
@pytest.mark.parametrize("cell", [Err("#N/A"), Formula(Err("#N/A"), "VLOOKUP(A1,[1]Sheet1!$A:$B,2,0)")],
                         ids=["plain-error", "formula-error"])
def test_poi_cell_that_is_an_error_value_is_rejected(tmp_path, cell):
    rows = [ledger_row(poi="RNT600001", uci="AURA", cable="88-224-4", weight=1.0),
            ledger_row(poi=cell, cable="88-448-4", weight=2.0)]
    with pytest.raises(LedgerError) as ei:
        parse(tmp_path, rows)
    assert re.search(r"row \d+: POI is an error value", str(ei.value)), str(ei.value)


# risk: medium
def test_rejection_messages_name_the_excel_row_number(tmp_path):
    # 假设：N 是 Excel 里看到的行号（表头为第 1 行），运维拿它直接去表里找；这份文件没有被跳过的空行
    ok = order_rows("RNT600001", [("A-1", 1.0)])
    bad_cont = ok + [ledger_row(cable="B-2", weight=2.0, subcon="SUBCO A")]
    with pytest.raises(LedgerError) as e1:
        parse(tmp_path, bad_cont, name="a.xlsx")
    assert "row 3: continuation row carries POI-level field" in str(e1.value)
    bad_poi = ok + [ledger_row(poi=Err("#N/A"), cable="B-2", weight=2.0)]
    with pytest.raises(LedgerError) as e2:
        parse(tmp_path, bad_poi, name="b.xlsx")
    assert "row 3: POI is an error value" in str(e2.value)


# ------------------------------------------------------------------ M-5 双指纹

# risk: high
def test_poi_record_has_raw_sha_field():
    assert "raw_sha" in {f.name for f in dataclasses.fields(PoiRecord)}


# risk: high
def test_both_fingerprints_are_stable_hex_for_the_same_file(tmp_path):
    a = parse(tmp_path, flat(three_orders()), name="a.xlsx")
    b = parse(tmp_path, flat(three_orders()), name="b.xlsx")
    assert {p.poi_no: (p.content_sha, p.raw_sha) for p in a.pois} == {p.poi_no: (p.content_sha, p.raw_sha) for p in b.pois}
    for p in a.pois:
        assert SHA_RE.match(p.content_sha) and SHA_RE.match(p.raw_sha)
        assert p.content_sha != p.raw_sha


# risk: high
@pytest.mark.parametrize("where", ["first-row", "continuation-row"])
def test_unmapped_executed_weight_changes_raw_sha_but_not_content_sha(tmp_path, where):
    def build(w):
        rows = order_rows("RNT600001", [("A-1", 1.0), ("B-2", 2.0)])
        rows[0 if where == "first-row" else 1][COLS["executed_2"]] = w  # 第二个 Executed Weight，不映射到任何字段
        return rows
    a = parse(tmp_path, build(72.0), name="a.xlsx").pois[0]
    b = parse(tmp_path, build(73.0), name="b.xlsx").pois[0]
    assert a.content_sha == b.content_sha
    assert a.raw_sha != b.raw_sha


# risk: medium
def test_raw_sha_ignores_order_position_and_follows_mapped_changes(tmp_path):
    g = three_orders()
    a = {p.poi_no: p for p in parse(tmp_path, flat(g), name="a.xlsx").pois}
    b = {p.poi_no: p for p in parse(tmp_path, flat([g[2], g[0], g[1]]), name="b.xlsx").pois}
    assert {k: v.raw_sha for k, v in a.items()} == {k: v.raw_sha for k, v in b.items()}
    g2 = three_orders()
    g2[0][1][COLS["weight"]] = 2.5  # 映射字段（第二段重量）变了：两个指纹都该变，别的单不动
    c = {p.poi_no: p for p in parse(tmp_path, flat(g2), name="c.xlsx").pois}
    assert c["RNT600001"].content_sha != a["RNT600001"].content_sha
    assert c["RNT600001"].raw_sha != a["RNT600001"].raw_sha
    assert c["RNT600002"].raw_sha == a["RNT600002"].raw_sha


# ------------------------------------------------------------------ L-1 计划重量列必须在 Recieve date 左边

# risk: high
def test_missing_planned_weight_group_is_rejected_not_filled_from_reference_group(tmp_path):
    headers = list(HEADERS)
    for c in ("min_1", "weight", "max_1"):  # 删掉计划组（第一组 Min Weight / Weight(T) / Maximum Weight）
        headers[COLS[c]] = "zz_" + headers[COLS[c]]
    rows = [ledger_row(poi="RNT600001", uci="AURA", cable="88-224-4", weight=2.064, ref_avg=2.057)]
    with pytest.raises(LedgerError) as ei:
        parse(tmp_path, rows, headers=headers)  # 只剩参考组的 Weight(T)：不能把 2.057 当 weight_t
    assert "Weight(T)" in str(ei.value)


# ------------------------------------------------------------------ L-2 occ_unparsed 新口径

# risk: high
def test_occ_unparsed_counts_only_statuses_with_week_or_date_pattern_that_parse_incompletely(tmp_path):
    rows = [ledger_row(poi="RNT600001", status=OCC_OK),
            ledger_row(poi="RNT600002", status="OCC ?"),
            ledger_row(poi="RNT600003", status="Completed"),
            ledger_row(poi="RNT600004"),
            ledger_row(poi="RNT600005", status=""),
            ledger_row(poi="RNT600006", status="OCC S48 - S49 2026/13/45 - 12/02")]  # 日期坏了
    res = parse(tmp_path, rows)
    assert res.occ_unparsed == 1
    assert by_no(res)["RNT600006"].status_raw == "OCC S48 - S49 2026/13/45 - 12/02"


# risk: medium
@pytest.mark.parametrize("status", ["OCC S48 - S49 2026/13/45 - 12/02", "OCC S48 2026/13/45", "OCC 2026/02/30"],
                         ids=["range-with-bad-date", "week-with-bad-date", "bad-date-only"])
def test_each_partially_broken_status_counts_once_and_never_raises(tmp_path, status):
    res = parse(tmp_path, [ledger_row(poi="RNT600001", status=status)])
    assert res.occ_unparsed == 1
    assert res.pois[0].status_raw == status
    assert res.pois[0].occ_date_from is None and res.pois[0].occ_date_to is None


# ------------------------------------------------------------------ L-4 t="d" 格

# risk: high
def test_iso_date_cell_in_an_unmapped_column_does_not_break_the_file(tmp_path):
    rows = [ledger_row(poi="RNT600001", uci="AURA", cable="88-224-4", weight=2.064, ref_avg=2.057,
                       avg_min=IsoDate("2026-11-25T00:00:00"))]  # Avg. Min 列不映射到任何字段
    res = parse(tmp_path, rows)
    assert len(res.pois) == 1
    assert res.pois[0].segments[0].weight_t == 2.064 and res.pois[0].segments[0].ref_avg_t == 2.057
