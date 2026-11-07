# risk: high
"""lutetia.poi_import：POI 台账映射、清洗、OCC 解析、内容哈希（Task 5.1，SCOPE-16 前半，SC-12）。
断言来自 DEV-PLAN Task 5.1 与 Product-Spec v1.8「POI 台账导入」「台账导入按表头名取列、清洗写法但原文另存」，不看实现。
fixture 全是合成值（工单号 RNT6000xx 为编造），表头次序与真表一致、复刻重名与拼写错误。
破了的代价：计划吨数取错列、工单被吞并或拆开、sha 不稳导致每次导入都误报「更新」。"""
import dataclasses
import json
import re
from datetime import date, timedelta

import pytest

from lutetia.poi_import import (LedgerError, LedgerParse, PoiRecord, SegmentRecord,
                                parse_ledger, parse_occ)
from xlsx_builder import (COLS, HEADERS, Blank, Err, Formula, ledger_row, with_header,
                          without_header, write_ledger)

OCC_OK = "OCC S48 - S49 2026/11/25 - 12/02"
REQUIRED = ["UCI", "POI", "Subcon", "Site Ville", "Commun", "Category", "Status", "Cable",
            "type infrastructure", "Length9(km)", "Weight(T)", "Recieve date", "Planned Operation Date"]


def parse(tmp_path, rows, headers=None, name="ledger.xlsx", **kw):
    return parse_ledger(write_ledger(tmp_path / name, rows, headers=headers, **kw))


def by_no(res):
    return {p.poi_no: p for p in res.pois}


def order_rows(poi, cables, uci="AURA", status=OCC_OK):
    """一个工单：首行带工单级字段与第一段，其余段各占一续行（POI 空）。cables 为 [(型号, 重量)]。"""
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


def spec_example_rows():
    """派单书例子：第 1 行带尾空格 UCI，第一个 Weight(T)=2.064，第二组 Weight(T)=2.057（公式缓存值）。"""
    return [
        ledger_row(uci="AURA ", subcon="SUBCO A", site_ville="TESTVILLE", commun="44000", poi="RNT600001",
                   category="Transport", status=OCC_OK, cable_category="Transport", cable="88-224-4",
                   infra="Aerial", length=1.5, min_1=9.1, weight=2.064, max_1=9.3,
                   received=45000, planned=45010, ref_min=1.9, ref_avg=Formula(2.057, "IFERROR(Z2*1,0)"),
                   ref_max=2.2),
        ledger_row(cable_category="Transport", cable="88-448-4", infra="Underground", length=2.0,
                   weight=3.5, ref_avg=2.9),
    ]


# ------------------------------------------------------------------ 契约与派单书例子

# risk: high
def test_record_types_expose_the_agreed_fields():
    def names(cls):
        assert dataclasses.is_dataclass(cls)
        return {f.name for f in dataclasses.fields(cls)}
    assert {"seq", "cable_category", "cable_type", "infra", "length_km", "weight_t", "ref_min_t",
            "ref_avg_t", "ref_max_t", "raw"} <= names(SegmentRecord)
    assert {"poi_no", "uci", "subcon", "site_ville", "commune_code", "category", "status_raw",
            "occ_week_from", "occ_week_to", "occ_date_from", "occ_date_to", "received_date",
            "planned_op_date", "content_sha", "raw", "segments"} <= names(PoiRecord)
    assert {"pois", "rows_read", "segment_count", "pois_without_segments", "cleaned", "occ_unparsed",
            "suspicious"} <= names(LedgerParse)
    assert issubclass(LedgerError, Exception)


# risk: high
def test_two_rows_become_one_order_with_two_segments(tmp_path):
    res = parse(tmp_path, spec_example_rows())
    assert isinstance(res, LedgerParse)
    assert len(res.pois) == 1
    p = res.pois[0]
    assert p.poi_no == "RNT600001" and p.uci == "AURA"
    assert len(p.segments) == 2
    s1, s2 = p.segments
    assert (s1.seq, s2.seq) == (1, 2)
    assert (s1.cable_type, s2.cable_type) == ("88-224-4", "88-448-4")
    assert (s1.infra, s2.infra) == ("Aerial", "Underground")
    assert (s1.length_km, s2.length_km) == (1.5, 2.0)
    # 计划重量取第一个 Weight(T)，参考平均取第二组（公式缓存值）
    assert s1.weight_t == 2.064 and s1.ref_avg_t == 2.057
    assert s2.weight_t == 3.5 and s2.ref_avg_t == 2.9
    assert res.segment_count == 2
    assert res.pois_without_segments == 0
    assert res.cleaned["uci_normalised"] == 1


# risk: high
def test_duplicate_headers_are_taken_by_occurrence(tmp_path):
    rows = [ledger_row(poi="RNT600001", category="CAT-POI", cable_category="CAT-CABLE-1", cable="88-224-4",
                       min_1=91.0, weight=2.064, max_1=93.0, executed_1=71.0, executed_2=72.0,
                       ref_min=1.9, ref_avg=2.057, ref_max=2.2),
            ledger_row(cable_category="CAT-CABLE-2", cable="88-448-4",
                       min_1=94.0, weight=3.5, max_1=96.0, ref_min=2.1, ref_avg=3.4, ref_max=3.9)]
    p = parse(tmp_path, rows).pois[0]
    assert p.category == "CAT-POI"  # 第 1 个 Category
    s1, s2 = p.segments
    assert (s1.cable_category, s2.cable_category) == ("CAT-CABLE-1", "CAT-CABLE-2")  # 第 2 个 Category
    assert (s1.weight_t, s1.ref_min_t, s1.ref_avg_t, s1.ref_max_t) == (2.064, 1.9, 2.057, 2.2)
    assert (s2.weight_t, s2.ref_min_t, s2.ref_avg_t, s2.ref_max_t) == (3.5, 2.1, 3.4, 3.9)


# risk: medium
def test_header_match_ignores_case_and_extra_whitespace(tmp_path):
    base = parse(tmp_path, spec_example_rows(), name="base.xlsx").pois[0]
    headers = with_header("uci", "  uci ")
    headers[COLS["poi"]] = "Poi"
    headers[COLS["site_ville"]] = "SITE   VILLE"
    headers[COLS["length"]] = "length9(KM)"
    headers[COLS["weight"]] = "WEIGHT(t)"
    headers[COLS["received"]] = "recieve DATE"
    headers[COLS["ref_avg"]] = " weight(T)  "  # 重名次序不因写法变化而乱
    p = parse(tmp_path, spec_example_rows(), headers=headers, name="variant.xlsx").pois[0]
    pick = lambda q: (q.poi_no, q.uci, q.site_ville, q.received_date,
                      [(s.seq, s.length_km, s.weight_t, s.ref_avg_t) for s in q.segments])
    assert pick(p) == pick(base)


# risk: high
def test_missing_poi_header_raises_with_column_name(tmp_path):
    with pytest.raises(LedgerError) as ei:
        parse(tmp_path, spec_example_rows(), headers=without_header("POI"))
    assert "missing column: POI" in str(ei.value)


# risk: high
def test_every_required_header_is_enforced_by_name(tmp_path):
    for name in REQUIRED:
        with pytest.raises(LedgerError) as ei:
            parse(tmp_path, spec_example_rows(), headers=without_header(name), name="m.xlsx")
        assert "missing column: %s" % name in str(ei.value), name


# ------------------------------------------------------------------ 工单与电缆段的切分

# risk: high
def test_order_without_cable_type_has_no_segments(tmp_path):
    rows = (order_rows("RNT600001", [("88-224-4", 1.0)])
            + order_rows("RNT600002", [])
            + order_rows("RNT600003", [("88-96-4", 2.0)]))
    res = parse(tmp_path, rows)
    got = by_no(res)
    assert got["RNT600002"].segments == []
    assert len(got["RNT600001"].segments) == 1 and len(got["RNT600003"].segments) == 1
    assert res.pois_without_segments == 1
    assert res.segment_count == 2


# risk: high
def test_continuation_rows_merge_and_seq_restarts_per_order(tmp_path):
    rows = (order_rows("RNT600001", [("A-1", 1.0), ("B-2", 2.0)])
            + [ledger_row(executed_1=5.0),  # 续行但没有电缆型号：并入上一单，不产生段、不占 seq
               ledger_row(cable="D-4", weight=4.0, ref_avg=4.0)]  # 同一单再续一段
            + order_rows("RNT600002", [("C-3", 3.0)]))
    res = parse(tmp_path, rows)
    got = by_no(res)
    assert len(res.pois) == 2
    assert [(s.seq, s.cable_type) for s in got["RNT600001"].segments] == [(1, "A-1"), (2, "B-2"), (3, "D-4")]
    assert [(s.seq, s.cable_type) for s in got["RNT600002"].segments] == [(1, "C-3")]
    assert res.segment_count == 4


# risk: high
def test_cable_on_a_later_row_only_still_makes_the_segment(tmp_path):
    rows = [ledger_row(poi="RNT600001", uci="AURA"), ledger_row(cable="88-448-4", weight=3.5)]
    res = parse(tmp_path, rows)
    p = res.pois[0]
    assert [(s.seq, s.cable_type, s.weight_t) for s in p.segments] == [(1, "88-448-4", 3.5)]
    assert res.pois_without_segments == 0


# risk: medium
def test_whitespace_only_cable_type_is_not_a_segment(tmp_path):
    # 新规则：电缆型号、电缆类别、基础设施类型、长度、重量五格全空才不产生段（这一行不带长度或重量）
    res = parse(tmp_path, [ledger_row(poi="RNT600001", cable="   ")])
    assert res.pois[0].segments == []
    assert res.pois_without_segments == 1 and res.segment_count == 0


# risk: high
def test_row_without_cable_type_but_with_length_and_weight_makes_a_segment(tmp_path):
    # 新规则（Spec v1.8）：型号、类别、基础设施、长度、重量任一非空就产生一个段；型号为空的段 cable_type=None
    rows = [ledger_row(poi="RNT600001", uci="AURA", cable="88-224-4", length=1.0, weight=1.5),
            ledger_row(length=1.5, weight=2.95),  # POI 空、Cable 空，但有长度和第一个 Weight(T)
            ledger_row(poi="RNT600003")]  # 五格全空的工单：仍然没有段
    res = parse(tmp_path, rows)
    got = by_no(res)
    s1, s2 = got["RNT600001"].segments
    assert (s1.seq, s1.cable_type) == (1, "88-224-4")
    assert (s2.seq, s2.cable_type, s2.weight_t, s2.length_km) == (2, None, 2.95, 1.5)
    assert got["RNT600003"].segments == []
    assert res.segment_count == 2
    assert res.pois_without_segments == 1  # 只有 RNT600003；RNT600001 有段不算
    assert res.cleaned["segment_no_cable_type"] == 1


# risk: high
def test_order_row_itself_carrying_only_weight_gets_one_segment_without_cable_type(tmp_path):
    rows = [ledger_row(poi="RNT600001", uci="AURA", cable="88-224-4", length=1.0, weight=1.5),
            ledger_row(length=1.5, weight=2.95),
            ledger_row(poi="RNT600002", uci="OUEST", weight=1.2),  # POI 行本身带 Weight(T) 但无 Cable
            ledger_row(poi="RNT600003")]
    res = parse(tmp_path, rows)
    got = by_no(res)
    assert [(s.seq, s.cable_type, s.weight_t) for s in got["RNT600002"].segments] == [(1, None, 1.2)]
    assert len(got["RNT600001"].segments) == 2 and got["RNT600003"].segments == []
    assert res.segment_count == 3
    assert res.pois_without_segments == 1
    assert res.cleaned["segment_no_cable_type"] == 2  # RNT600001 的第 2 段 + RNT600002 的唯一段


# risk: high
@pytest.mark.parametrize("cell", [
    {"cable_category": "Transport"},
    {"infra": "Aerial"},
    {"length": 1.5},
    {"weight": 2.0},
    {"cable": "   ", "weight": 1.0},  # 型号只有空白：清洗成空，但重量非空，照样有段
], ids=["cable-category-only", "infra-only", "length-only", "weight-only", "blank-cable-text-plus-weight"])
def test_any_one_of_the_five_cells_makes_a_segment_with_null_cable_type(tmp_path, cell):
    res = parse(tmp_path, [ledger_row(poi="RNT600001", uci="AURA", **cell)])
    segs = res.pois[0].segments
    assert len(segs) == 1 and segs[0].seq == 1 and segs[0].cable_type is None
    assert res.segment_count == 1 and res.pois_without_segments == 0
    assert res.cleaned["segment_no_cable_type"] == 1


# risk: medium
def test_blank_rows_are_ignored(tmp_path):
    rows = [ledger_row(poi="RNT600001", cable="88-224-4", weight=1.0),
            None,  # 整行不写（行号被占）
            [None] * len(HEADERS),  # 空 <row/>
            [Blank()] * len(HEADERS),  # 只有带样式的空格
            ledger_row(poi="RNT600002", cable="88-448-4", weight=2.0)]
    res = parse(tmp_path, rows)
    got = by_no(res)
    assert sorted(got) == ["RNT600001", "RNT600002"]
    assert len(got["RNT600001"].segments) == 1 and len(got["RNT600002"].segments) == 1
    assert res.segment_count == 2 and res.pois_without_segments == 0


# risk: medium
def test_rows_read_counts_data_rows_without_header(tmp_path):
    # 假设：rows_read = 表头之后读到的数据行数（Spec 说「191 行 117 单」按数据行数口径）
    rows = order_rows("RNT600001", [("A-1", 1.0), ("B-2", 2.0)]) + order_rows("RNT600002", [("C-3", 3.0)])
    assert parse(tmp_path, rows).rows_read == 3


# ------------------------------------------------------------------ 清洗

# risk: high
def test_na_error_cells_become_none_and_are_counted(tmp_path):
    rows = [ledger_row(poi="RNT600001", uci="AURA", subcon=Err("#N/A"), cable="88-224-4", weight=2.0,
                       ref_min=Err("#N/A"),
                       ref_avg=Formula(Err("#N/A"), "VLOOKUP(A1,[1]Sheet1!$A:$B,2,0)"), ref_max=2.2)]
    res = parse(tmp_path, rows)
    p = res.pois[0]
    s = p.segments[0]
    assert p.subcon is None
    assert s.ref_min_t is None and s.ref_avg_t is None  # 错误值不得被当成数
    assert s.ref_max_t == 2.2 and s.weight_t == 2.0
    assert res.cleaned["na_to_empty"] == 3


# risk: medium
def test_na_in_date_and_length_cells_gives_none(tmp_path):
    rows = [ledger_row(poi="RNT600001", cable="88-224-4", weight=2.0, length=Err("#N/A"),
                       received=Err("#N/A"), planned=Err("#N/A"))]
    p = parse(tmp_path, rows).pois[0]
    assert p.received_date is None and p.planned_op_date is None
    assert p.segments[0].length_km is None


# risk: medium
def test_empty_and_blank_strings_become_none(tmp_path):
    rows = [ledger_row(poi="RNT600001", uci="AURA", subcon="", site_ville="   ", commun="",
                       cable="88-224-4", cable_category="", infra="", weight=1.0)]
    p = parse(tmp_path, rows).pois[0]
    assert p.subcon is None and p.site_ville is None and p.commune_code is None
    assert p.segments[0].cable_category is None and p.segments[0].infra is None


# risk: high
def test_text_is_trimmed_and_inner_whitespace_compressed(tmp_path):
    rows = [ledger_row(poi="RNT600001", uci="AURA", subcon="SUBCO A ", site_ville=" TESTVILLE",
                       cable="88-224-4 ", weight=1.0),
            ledger_row(poi="RNT600002", uci="AURA", site_ville="Saint   Test\t Ville")]
    got = by_no(parse(tmp_path, rows))
    assert got["RNT600001"].subcon == "SUBCO A"
    assert got["RNT600001"].site_ville == "TESTVILLE"
    assert got["RNT600001"].segments[0].cable_type == "88-224-4"
    assert got["RNT600002"].site_ville == "Saint Test Ville"


# risk: medium
def test_trimmed_cells_counts_only_cells_that_changed(tmp_path):
    dirty = [ledger_row(poi="RNT600001", uci="AURA", subcon="SUBCO A ", site_ville=" TESTVILLE")]
    assert parse(tmp_path, dirty, name="d.xlsx").cleaned["trimmed_cells"] == 2
    clean = parse(tmp_path, order_rows("RNT600001", [("A-1", 1.0)]), name="c.xlsx")
    assert clean.cleaned == {"uci_normalised": 0, "trimmed_cells": 0, "na_to_empty": 0,
                             "segment_no_cable_type": 0, "not_a_number": 0}


# risk: high
def test_uci_is_uppercased_and_stripped_and_counted_when_changed(tmp_path):
    rows = [ledger_row(poi="RNT600001", uci="AURA "), ledger_row(poi="RNT600002", uci="Ouest"),
            ledger_row(poi="RNT600003", uci="OUEST"), ledger_row(poi="RNT600004", uci="aura")]
    res = parse(tmp_path, rows)
    got = by_no(res)
    assert [got["RNT60000%d" % i].uci for i in (1, 2, 3, 4)] == ["AURA", "OUEST", "OUEST", "AURA"]
    assert res.cleaned["uci_normalised"] == 3  # 只数真被改动的格：AURA 尾空格、Ouest、aura


# risk: high
def test_commune_code_numeric_cell_becomes_string_without_decimals(tmp_path):
    rows = [ledger_row(poi="RNT600001", commun=44109), ledger_row(poi="RNT600002", commun=44109.0),
            ledger_row(poi="RNT600003", commun="2A004"), ledger_row(poi="RNT600004", commun="01234"),
            ledger_row(poi="RNT600005")]
    got = by_no(parse(tmp_path, rows))
    assert [got["RNT60000%d" % i].commune_code for i in (1, 2, 3, 4, 5)] == \
        ["44109", "44109", "2A004", "01234", None]


# risk: high
def test_excel_serial_dates_become_dates_from_1899_12_30(tmp_path):
    assert date(1899, 12, 30) + timedelta(days=45000) == date(2023, 3, 15)  # 锚点：Excel 45000 = 2023-03-15
    rows = [ledger_row(poi="RNT600001", received=45000, planned=45010.0),
            ledger_row(poi="RNT600002", received=date(2026, 11, 5), planned=46000.75),
            ledger_row(poi="RNT600003")]
    got = by_no(parse(tmp_path, rows))
    a, b, c = got["RNT600001"], got["RNT600002"], got["RNT600003"]
    assert (a.received_date, a.planned_op_date) == (date(2023, 3, 15), date(2023, 3, 25))
    assert type(a.received_date) is date and type(a.planned_op_date) is date
    assert b.received_date == date(2026, 11, 5)
    assert b.planned_op_date == date(1899, 12, 30) + timedelta(days=46000)  # 带时间的序号只取日期
    assert type(b.planned_op_date) is date
    assert c.received_date is None and c.planned_op_date is None


# risk: medium
def test_suspicious_poi_numbers_are_listed_not_rewritten(tmp_path):
    rows = [ledger_row(poi="RNT600001"), ledger_row(poi="RNT60001"), ledger_row(poi="RNT6000012"),
            ledger_row(poi="RNT600004 "), ledger_row(poi="rnt600005"), ledger_row(poi="ABC123456")]
    res = parse(tmp_path, rows)
    assert res.suspicious == ["RNT60001", "RNT6000012", "rnt600005"]
    nos = [p.poi_no for p in res.pois]
    assert "RNT60001" in nos and "RNT6000012" in nos and "rnt600005" in nos  # 原样不改写
    assert "RNT600004" in nos  # 尾空格先清洗，清洗后合规，不算可疑


# risk: high
def test_raw_keeps_original_text_and_is_json_storable(tmp_path):
    rows = spec_example_rows()
    rows[0][COLS["subcon"]] = Err("#N/A")
    p = parse(tmp_path, rows).pois[0]
    assert isinstance(p.raw, dict) and isinstance(p.segments[0].raw, dict)
    poi_json = json.dumps(p.raw)  # 日期序号、#N/A 都得是 JSON 可存类型，不加 default
    seg_json = json.dumps(p.segments[0].raw)
    assert '"AURA "' in poi_json and '"RNT600001"' in poi_json  # 原文另存：清洗不改 raw
    assert '"88-224-4"' in seg_json
    json.dumps(p.segments[1].raw)


# ------------------------------------------------------------------ OCC 状态在台账里的落地

# risk: high
def test_status_text_is_kept_and_occ_fields_filled(tmp_path):
    rows = [ledger_row(poi="RNT600001", status=OCC_OK), ledger_row(poi="RNT600002", status="OCC ?"),
            ledger_row(poi="RNT600003", status="Completed"), ledger_row(poi="RNT600004")]
    got = by_no(parse(tmp_path, rows))
    a = got["RNT600001"]
    assert a.status_raw == OCC_OK
    assert (a.occ_week_from, a.occ_week_to, a.occ_date_from, a.occ_date_to) == \
        (48, 49, date(2026, 11, 25), date(2026, 12, 2))
    for no, raw in (("RNT600002", "OCC ?"), ("RNT600003", "Completed"), ("RNT600004", None)):
        p = got[no]
        assert p.status_raw == raw
        assert (p.occ_week_from, p.occ_week_to, p.occ_date_from, p.occ_date_to) == (None, None, None, None)


# risk: medium
def test_status_without_week_or_date_pattern_is_not_counted_as_unparsed(tmp_path):
    # 新口径（L-2）：OCC ? / Completed / 空状态里根本没有周号或日期样式，不算「解析不完整」，不计数、不抛错
    rows = [ledger_row(poi="RNT600001", status=OCC_OK), ledger_row(poi="RNT600002", status="OCC ?"),
            ledger_row(poi="RNT600003", status="Completed"), ledger_row(poi="RNT600004")]
    res = parse(tmp_path, rows, name="both.xlsx")
    assert res.occ_unparsed == 0
    assert by_no(res)["RNT600002"].status_raw == "OCC ?"


# ------------------------------------------------------------------ parse_occ

NONE4 = (None, None, None, None)


# risk: high
@pytest.mark.parametrize("text,expected", [
    ("OCC S48 - S49 2026/11/25 - 12/02", (48, 49, date(2026, 11, 25), date(2026, 12, 2))),
    ("OCC S45 2026/11/5", (45, 45, date(2026, 11, 5), date(2026, 11, 5))),  # 单周号 to=from、单日期 to=from
    ("OCC ?", NONE4),
    ("OCC S49 - S50 202611/25 - 12/04", (49, 50, date(2026, 11, 25), date(2026, 12, 4))),  # 缺斜杠笔误
    ("Completed", NONE4),
    ("", NONE4),
    (None, NONE4),
    ("   ", NONE4),
], ids=["week-range", "single-week-single-day", "question-mark", "missing-slash", "completed",
        "empty", "none", "blank"])
def test_parse_occ_agreed_formats(text, expected):
    assert parse_occ(text) == expected


# risk: medium
@pytest.mark.parametrize("text,expected", [
    ("OCC S50", (50, 50, None, None)),
    ("OCC 2026/11/23 - 12/01", (None, None, date(2026, 11, 23), date(2026, 12, 1))),
    ("OCC S48-S49 2026/11/25-12/02", (48, 49, date(2026, 11, 25), date(2026, 12, 2))),
    ("OCC S48 - S49 2026/11/25 - 2026/12/02", (48, 49, date(2026, 11, 25), date(2026, 12, 2))),
    ("OCC S2 - S3 2026/1/5 - 1/9", (2, 3, date(2026, 1, 5), date(2026, 1, 9))),
    ("OCC S48 2026/13/45", (48, 48, None, None)),  # 不存在的日期：留空，不抛 ValueError
], ids=["week-only", "dates-only", "no-spaces", "both-years", "single-digits", "impossible-date"])
def test_parse_occ_handwritten_variants(text, expected):
    assert parse_occ(text) == expected


# risk: medium
def test_parse_occ_second_date_without_year_rolls_into_next_year():
    # 假设（Spec 只说第二个日期可省年份）：跨年时省略的年份取下一年，否则 date_to 会早于 date_from
    wf, wt, d1, d2 = parse_occ("OCC S52 - S01 2026/12/28 - 01/04")
    assert (wf, wt, d1) == (52, 1, date(2026, 12, 28))
    assert d2 == date(2027, 1, 4)


# ------------------------------------------------------------------ content_sha

SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def three_orders():
    return [order_rows("RNT600001", [("A-1", 1.0), ("B-2", 2.0)]),
            order_rows("RNT600002", [("C-3", 3.0)], uci="OUEST", status="OCC ?"),
            order_rows("RNT600003", [])]


def shas(res):
    return {p.poi_no: p.content_sha for p in res.pois}


def flat(groups):
    return [r for g in groups for r in g]


# risk: high
def test_content_sha_is_stable_hex_and_distinct_per_order(tmp_path):
    a = shas(parse(tmp_path, flat(three_orders()), name="a.xlsx"))
    b = shas(parse(tmp_path, flat(three_orders()), name="b.xlsx"))
    assert a == b  # 同样内容两次解析一致（不含导入时间）
    assert all(SHA_RE.match(v) for v in a.values())
    assert len(set(a.values())) == 3


# risk: high
def test_content_sha_changes_only_for_the_order_whose_segment_weight_changed(tmp_path):
    before = shas(parse(tmp_path, flat(three_orders()), name="a.xlsx"))
    groups = three_orders()
    groups[0][1][COLS["weight"]] = 2.5  # RNT600001 第二段的重量 2.0 -> 2.5
    after = shas(parse(tmp_path, flat(groups), name="b.xlsx"))
    assert after["RNT600001"] != before["RNT600001"]
    assert after["RNT600002"] == before["RNT600002"] and after["RNT600003"] == before["RNT600003"]


# risk: high
def test_content_sha_ignores_order_of_orders_in_the_file(tmp_path):
    g = three_orders()
    a = shas(parse(tmp_path, flat(g), name="a.xlsx"))
    b = shas(parse(tmp_path, flat([g[2], g[0], g[1]]), name="b.xlsx"))
    assert a == b


# risk: medium
def test_content_sha_tracks_order_fields_and_segment_sequence(tmp_path):
    before = shas(parse(tmp_path, flat(three_orders()), name="a.xlsx"))
    groups = three_orders()
    groups[1][0][COLS["status"]] = "OCC S50 2026/12/10"  # 只改 RNT600002 的状态
    after = shas(parse(tmp_path, flat(groups), name="b.xlsx"))
    assert after["RNT600002"] != before["RNT600002"]
    assert after["RNT600001"] == before["RNT600001"]
    # 段是有序的：同样两段换个先后，seq 对应的内容变了，sha 要变
    ab = order_rows("RNT600001", [("A-1", 1.0), ("B-2", 2.0)])
    ba = order_rows("RNT600001", [("B-2", 2.0), ("A-1", 1.0)])
    sa = shas(parse(tmp_path, ab, name="ab.xlsx"))["RNT600001"]
    sb = shas(parse(tmp_path, ba, name="ba.xlsx"))["RNT600001"]
    assert sa != sb


# ------------------------------------------------------------------ 可变默认值

# risk: medium
def test_results_do_not_share_mutable_state(tmp_path):
    dirty = parse(tmp_path, [ledger_row(poi="RNT60001")], name="a.xlsx")
    assert dirty.suspicious == ["RNT60001"]
    clean = parse(tmp_path, [ledger_row(poi="RNT600001"), ledger_row(poi="RNT600002")], name="b.xlsx")
    assert clean.suspicious == []
    p1, p2 = clean.pois
    assert p1.segments == [] and p1.segments is not p2.segments
    p1.segments.append("x")
    assert p2.segments == []
