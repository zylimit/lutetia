"""POI 台账解析：按表头名取列、清洗写法但原文另存（raw）、解析 OCC 状态、算内容哈希与原文哈希。
纯函数、不碰数据库；日志只记行号与列名，不打印行内容（台账是真实业务数据）。清洗小函数在 poi_clean。
"""
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field, fields
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from lutetia.poi_clean import Cleaner, new_counts, occ_incomplete, parse_occ
from lutetia.xlsx_min import XlError, read_first_sheet

log = logging.getLogger(__name__)

POI_NO_RE = re.compile(r"[A-Z]{3}[0-9]{6}")
# 必需表头，按此顺序报缺失。拼写 Recieve date、Length9(km) 是台账原样拼写，不是笔误，不要改。
REQUIRED = ["UCI", "POI", "Subcon", "Site Ville", "Commun", "Category", "Status", "Cable",
            "type infrastructure", "Length9(km)", "Weight(T)", "Recieve date", "Planned Operation Date"]
# 第二次出现的重名列（参考重量组、电缆类别）：不在必需清单里，缺了置空并记警告
SECOND = ["Category", "Min Weight", "Weight(T)", "Maximum Weight"]
# 工单级字段：只该出现在 POI 号非空的行上；续行带了说明这一行归属不明
POI_LEVEL = ["Subcon", "Site Ville", "Commun", "Status"]


class LedgerError(Exception):
    """台账结构不对（缺表头、行归属不明）。"""


@dataclass
class SegmentRecord:
    seq: int
    cable_category: Optional[str] = None
    cable_type: Optional[str] = None
    infra: Optional[str] = None
    length_km: Optional[float] = None
    weight_t: Optional[float] = None
    ref_min_t: Optional[float] = None
    ref_avg_t: Optional[float] = None
    ref_max_t: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PoiRecord:
    poi_no: str
    uci: Optional[str] = None
    subcon: Optional[str] = None
    site_ville: Optional[str] = None
    commune_code: Optional[str] = None
    category: Optional[str] = None
    status_raw: Optional[str] = None
    occ_week_from: Optional[int] = None
    occ_week_to: Optional[int] = None
    occ_date_from: Optional[date] = None
    occ_date_to: Optional[date] = None
    received_date: Optional[date] = None
    planned_op_date: Optional[date] = None
    content_sha: str = ""
    raw_sha: str = ""   # 工单 raw 与有序各段 raw 的指纹；未映射列（如 Executed Weight）变了它会变、content_sha 不变
    raw: Dict[str, Any] = field(default_factory=dict)
    segments: List[SegmentRecord] = field(default_factory=list)


@dataclass
class LedgerParse:
    pois: List[PoiRecord] = field(default_factory=list)
    rows_read: int = 0            # 表头之后、非空的数据行数
    segment_count: int = 0
    pois_without_segments: int = 0
    cleaned: Dict[str, int] = field(default_factory=new_counts)
    occ_unparsed: int = 0         # 状态文本里有周号 / 日期样式却没解析完整的工单数
    suspicious: List[str] = field(default_factory=list)  # 不合 ^[A-Z]{3}\d{6}$ 的工单号，原样不改


def _norm(h: Any) -> str:
    return " ".join(str(h).split()).lower()


def _locate(header: List[Any]) -> Tuple[Dict[str, int], Dict[str, Optional[int]], List[Tuple[str, int]]]:
    """表头行 -> (必需列位置, 第二次出现的列位置, raw 用的 [(键, 列)])。重名列按出现次序取。"""
    where: Dict[str, List[int]] = {}
    named: List[Tuple[str, int]] = []
    seen: Dict[str, int] = {}
    for col, h in enumerate(header):
        if h is None or not str(h).strip():
            continue
        where.setdefault(_norm(h), []).append(col)
        base = " ".join(str(h).split())
        seen[base] = seen.get(base, 0) + 1
        named.append((base if seen[base] == 1 else "%s (%d)" % (base, seen[base]), col))
    first: Dict[str, int] = {}
    for name in REQUIRED:
        if _norm(name) not in where:
            raise LedgerError("missing column: %s" % name)
        first[name] = where[_norm(name)][0]
    if first["Weight(T)"] > first["Recieve date"]:
        # 计划重量组（第一个 Weight(T)）在 Recieve date 左边；只剩右边的参考组时，不能把参考重量当计划重量
        raise LedgerError("Weight(T): planned-weight column not found left of Recieve date")
    second: Dict[str, Optional[int]] = {}
    for name in SECOND:
        cols = where.get(_norm(name), [])
        second[name] = cols[1] if len(cols) > 1 else None
        if second[name] is None:
            log.warning("second '%s' column not found, values left empty", name)
    return first, second, named


def _at(row: List[Any], col: Optional[int]) -> Any:
    return row[col] if col is not None and col < len(row) else None


def _raw(named: List[Tuple[str, int]], row: List[Any]) -> Dict[str, Any]:
    vals = {key: _at(row, col) for key, col in named}
    return {k: str(v) if isinstance(v, str) else v for k, v in vals.items()}  # XlError 转普通 str，其余原样


def _digest(body: Any) -> str:
    """规范化 JSON（键排序、紧凑、不转义中文）的 sha256；同样内容永远同一个值。"""
    blob = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                      default=lambda o: o.isoformat())
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _content_sha(poi: PoiRecord) -> str:
    """工单字段 + 有序电缆段（清洗后的值）；不含 raw 与导入时间。"""
    skip = {"content_sha", "raw_sha", "raw", "segments"}
    body = {f.name: getattr(poi, f.name) for f in fields(PoiRecord) if f.name not in skip}
    body["segments"] = [{f.name: getattr(s, f.name) for f in fields(SegmentRecord) if f.name != "raw"}
                        for s in poi.segments]
    return _digest(body)


def _raw_sha(poi: PoiRecord) -> str:
    """工单 raw 与有序各段 raw（原文）；没映射到字段的列变了也会变。"""
    return _digest({"raw": poi.raw, "segments": [s.raw for s in poi.segments]})


def parse_ledger(path: Any) -> LedgerParse:
    """读台账第一个工作表。POI 号非空的行开新工单，空的并入上一单；型号 / 类别 / 基础设施 / 长度 / 重量
    任一格清洗后非空的行产生电缆段。

    缺必需表头 / 行归属不明 / POI 是错误值 / 同一 POI 号出现两次抛 LedgerError，信息里的行号是 Excel
    行号（表头为第 1 行；读取器按行号对齐，跳过空行不会漂移）；xlsx 本身读不了抛 XlsxError。
    """
    rows = read_first_sheet(path)
    if not rows:
        raise LedgerError("empty sheet: no header row")
    c, second, named = _locate(rows[0])
    cl = Cleaner()
    res = LedgerParse(cleaned=cl.counts)
    current: Optional[PoiRecord] = None
    first_row: Dict[str, int] = {}
    for number, row in enumerate(rows[1:], start=2):
        if all(v is None or (isinstance(v, str) and not v.strip()) for v in row):
            continue  # 空行（整行缺失 / 只有样式）
        res.rows_read += 1
        cl.row = number
        poi_cell = _at(row, c["POI"])
        if isinstance(poi_cell, XlError):
            raise LedgerError("row %d: POI is an error value" % number)
        poi_no = cl.text(poi_cell)
        if poi_no is not None:
            if poi_no in first_row:
                raise LedgerError("row %d: duplicate POI number (first seen at row %d)" % (number, first_row[poi_no]))
            first_row[poi_no] = number
            current = PoiRecord(
                poi_no=poi_no,
                uci=cl.uci(_at(row, c["UCI"])),
                subcon=cl.text(_at(row, c["Subcon"])),
                site_ville=cl.text(_at(row, c["Site Ville"])),
                commune_code=cl.text(_at(row, c["Commun"])),
                category=cl.text(_at(row, c["Category"])),
                status_raw=cl.text(_at(row, c["Status"])),
                received_date=cl.excel_date(_at(row, c["Recieve date"]), "Recieve date"),
                planned_op_date=cl.excel_date(_at(row, c["Planned Operation Date"]), "Planned Operation Date"),
                raw=_raw(named, row))
            res.pois.append(current)
        elif current is None:
            raise LedgerError("row %d: no POI above" % number)
        elif any(cl.text(_at(row, c[k])) is not None for k in POI_LEVEL):
            raise LedgerError("row %d: continuation row carries POI-level field" % number)
        cable = cl.text(_at(row, c["Cable"]))
        cat = cl.text(_at(row, second["Category"]))
        infra = cl.text(_at(row, c["type infrastructure"]))
        length, has_length = cl.numeric(_at(row, c["Length9(km)"]), "Length9(km)")
        weight, has_weight = cl.numeric(_at(row, c["Weight(T)"]), "Weight(T)")
        if not any((cable, cat, infra, has_length, has_weight)):
            continue  # 这五格清洗后全空才不是电缆段（Executed Weight 等其它列不算）
        if cable is None:
            cl.counts["segment_no_cable_type"] += 1  # 有长度 / 重量却没型号：不悄悄丢，计数让导入报告看得见
        # 参考重量三列不参与成段判断，只在成段时才清洗并计数（文本 / #N/A 计入 not_a_number / na_to_empty）
        current.segments.append(SegmentRecord(
            seq=len(current.segments) + 1, cable_category=cat, cable_type=cable, infra=infra,
            length_km=length, weight_t=weight,
            ref_min_t=cl.numeric(_at(row, second["Min Weight"]), "Min Weight")[0],
            ref_avg_t=cl.numeric(_at(row, second["Weight(T)"]), "Weight(T) #2")[0],
            ref_max_t=cl.numeric(_at(row, second["Maximum Weight"]), "Maximum Weight")[0],
            raw=_raw(named, row)))
    for poi in res.pois:
        if not POI_NO_RE.fullmatch(poi.poi_no):
            res.suspicious.append(poi.poi_no)
        parsed = parse_occ(poi.status_raw)
        poi.occ_week_from, poi.occ_week_to, poi.occ_date_from, poi.occ_date_to = parsed
        if occ_incomplete(poi.status_raw, parsed):
            res.occ_unparsed += 1
        poi.content_sha = _content_sha(poi)
        poi.raw_sha = _raw_sha(poi)
        res.segment_count += len(poi.segments)
        res.pois_without_segments += 0 if poi.segments else 1
    return res
