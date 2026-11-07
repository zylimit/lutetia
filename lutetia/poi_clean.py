"""POI 台账的单元格清洗与 OCC 状态解析（从 poi_import 拆出来，纯函数 / 小类，不碰文件与数据库）。
日志只记行号与列名，不打印单元格内容（台账是真实业务数据）。
"""
import logging
import math
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from lutetia.xlsx_min import XlError

log = logging.getLogger(__name__)

EXCEL_EPOCH = date(1899, 12, 30)  # Excel 日期序号 0 的日历日（含 1900 闰年 bug 的修正）

_WEEK_RE = re.compile(r"(?<![A-Za-z0-9])S(\d{1,2})(?!\d)", re.IGNORECASE)
# 三种日期写法：yyyy/m/d、缺斜杠的笔误 yyyymm/d、省年份的 m/d（只许作第二个日期）
_DATE_RE = re.compile(r"(?<!\d)(?:(\d{4})/(\d{1,2})/(\d{1,2})|(\d{4})(\d{2})/(\d{1,2})|(\d{1,2})/(\d{1,2}))(?!\d)")
# 宽松的「长得像周号 / 日期」，只用来判断文本里有没有这类样式（有样式却没解析完整才算失败）
_WEEK_LIKE = re.compile(r"(?<![A-Za-z0-9])S\d+", re.IGNORECASE)
_DATE_LIKE = re.compile(r"\d+\s*[/.\-]\s*\d+")

OccParts = Tuple[Optional[int], Optional[int], Optional[date], Optional[date]]


def _make_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:  # 13 月、45 日这类手写错误：留空，不报错
        return None


def parse_occ(text: Optional[str]) -> OccParts:
    """OCC 状态文本 -> (周号起, 周号止, 日期起, 日期止)；只有一个值时止 = 起，认不出的字段为 None。"""
    if not text or not text.strip():
        return (None, None, None, None)
    weeks = [int(w) for w in _WEEK_RE.findall(text)][:2]
    if any(not 1 <= w <= 53 for w in weeks):
        weeks = []
    found: List[Tuple[Optional[int], int, int]] = []
    for m in _DATE_RE.finditer(text):
        g = m.groups()
        if g[0]:
            found.append((int(g[0]), int(g[1]), int(g[2])))
        elif g[3]:
            found.append((int(g[3]), int(g[4]), int(g[5])))
        else:
            found.append((None, int(g[6]), int(g[7])))
    date_from = date_to = None
    if found and found[0][0] is not None:
        date_from = date_to = _make_date(*found[0])
    if len(found) > 1:
        y, mo, d = found[1]
        inherited = y is None
        y = found[0][0] if inherited else y  # 省了年份就借第一个日期的；第一个也没年份就没法补，留空
        date_to = _make_date(y, mo, d) if y is not None else None
        if inherited and date_to and date_from and date_to < date_from:  # 跨年（12/28 - 01/04）取下一年
            date_to = _make_date(y + 1, mo, d)
        if date_from is None or date_to is None:  # 区间只认出一端会被当成单日误用，坏一个就两个都留空
            date_from = date_to = None
    return (weeks[0] if weeks else None, weeks[-1] if weeks else None, date_from, date_to)


def occ_incomplete(text: Optional[str], parsed: OccParts) -> bool:
    """文本里有周号样式却没认出周号、或有日期样式却没认全日期（含只坏一个）。OCC ? / Completed / 空都不算。"""
    if not text:
        return False
    week_from, _wt, date_from, date_to = parsed
    return bool((_WEEK_LIKE.search(text) and week_from is None)
                or (_DATE_LIKE.search(text) and (date_from is None or date_to is None)))


def new_counts() -> Dict[str, int]:
    return {"uci_normalised": 0, "trimmed_cells": 0, "na_to_empty": 0, "segment_no_cable_type": 0,
            "not_a_number": 0}


def to_text(v: Any) -> str:
    if isinstance(v, float) and v.is_integer():
        return str(int(v))  # 44109.0 -> "44109"，不留小数点
    return str(v)


class Cleaner:
    """单元格清洗并累计计数。row 是当前行号，只用于警告里定位（不带内容）。"""

    def __init__(self) -> None:
        self.counts = new_counts()
        self.row = 0

    def _empty(self, v: Any) -> bool:
        if v is None:  # 缺格本来就是空，不算「清洗」
            return True
        if isinstance(v, XlError) or (isinstance(v, str) and not v.strip()):
            self.counts["na_to_empty"] += 1
            return True
        return False

    def text(self, v: Any, count_trim: bool = True) -> Optional[str]:
        if self._empty(v):
            return None
        s = to_text(v)
        out = " ".join(s.split())
        if out != s and count_trim:
            self.counts["trimmed_cells"] += 1
        return out

    def uci(self, v: Any) -> Optional[str]:
        s = self.text(v, count_trim=False)
        if s is None:
            return None
        out = s.upper()
        if out != to_text(v):  # UCI 的任何改动只计 uci_normalised，不重复计入 trimmed_cells
            self.counts["uci_normalised"] += 1
        return out

    def numeric(self, v: Any, column: str) -> Tuple[Optional[float], bool]:
        """-> (数值或 None, 这一格清洗后有没有内容)。

        有内容 = 不是缺格 / 空白 / #N/A 错误值；文本 n/a 之类有内容但转不成数，值为 None 并计 not_a_number。
        成段看「有没有内容」而不是「转没转成数」，否则一个文本格就让整段（连同别的字段）消失。
        """
        if self._empty(v):
            return None, False
        f = None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            f = float(v)
        elif isinstance(v, str):
            try:
                f = float(v)
            except ValueError:
                pass
        if f is not None and math.isfinite(f):
            return f, True
        self.counts["not_a_number"] += 1
        log.warning("row %d: column %s is not a number, left empty", self.row, column)
        return None, True

    def excel_date(self, v: Any, column: str) -> Optional[date]:
        if self._empty(v):
            return None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            try:
                return EXCEL_EPOCH + timedelta(days=math.floor(v))  # 带时间的序号只取日期
            except (OverflowError, ValueError):
                pass
        log.warning("row %d: column %s is not an Excel date, left empty", self.row, column)
        return None
