"""SLA 流程模板导入：DEPOSE-Transportation / Distribution / MASSIVE 三份 xlsx → sla_template_step。
按表头名取列（Number* / Name* / SLA典型时长 / Responsible party*），第一个工作表。模板名取自文件名（DEPOSE-<模板>.xlsx）。
纯解析 + 一个事务的整模板替换；错误信息和日志只带行号、列名与计数，不带单元格内容（SLA 表只在欧洲境内的库里）。
时长原文另解析成 数值 + 单位（Decisions 2026-11-10：界面只英法，前端按语言显示），解析不了两者为 NULL，原文照存。
"""
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .xlsx_min import read_first_sheet

log = logging.getLogger(__name__)

TEMPLATES = ("Transportation", "Distribution", "MASSIVE")
# 表头名是 DEPOSE 表的原样写法（含星号与中文），不是笔误
COL_SEQ, COL_STEP, COL_SLA, COL_OWNER = "Number*", "Name*", "SLA典型时长", "Responsible party*"
REQUIRED = [COL_SEQ, COL_STEP, COL_SLA, COL_OWNER]
OWNERS = {"客户": "customer", "华为": "huawei", "合作方": "partner"}
NAME_RE = re.compile(r"^DEPOSE-(.+)\.xlsx$", re.IGNORECASE)

# ---- 时长解析 ---------------------------------------------------------------------------------------------------------
# sla_unit 的取值（与 007 迁移的 CHECK 一致）。tonne_per_day 是拆除节点的「每天几吨」产能写法，不是时长，单列一个单位。
UNITS = ("minute", "hour", "day", "workday", "week", "month", "tonne_per_day")
# 单位写法 → 单位；正则里按长度降序排，「工作日」先于「日」、「hours」先于「h」
UNIT_WORDS = {
    "个工作日": "workday", "工作日": "workday", "自然日": "day", "天": "day", "日": "day",
    # 只认「个月」：单独的「月」前面接数字是月份名（「二月」「2月」= 二月份），不是时长（审查 L-2）
    "个小时": "hour", "小时": "hour", "分钟": "minute", "个星期": "week", "星期": "week", "周": "week", "个月": "month",
    "workingdays": "workday", "workingday": "workday", "workdays": "workday", "workday": "workday", "wd": "workday",
    "days": "day", "day": "day", "d": "day", "hours": "hour", "hour": "hour", "h": "hour",
    "minutes": "minute", "minute": "minute", "min": "minute", "weeks": "week", "week": "week", "months": "month", "month": "month",
}
CN_DIGITS = {"一": "1", "二": "2", "两": "2", "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}
_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = "(%s)" % "|".join(sorted((re.escape(w) for w in UNIT_WORDS), key=len, reverse=True))
DURATION_RE = re.compile(r"^(?:≤|<=|<|不超过|最多|最长|约)?%s(?:[-~至到]%s)?%s(?:内|以内|之内)?$" % (_NUM, _NUM, _UNIT))
RATE_RE = re.compile(r"^%s(?:吨|t)/(?:天|日|d|day)$" % _NUM)


# 冒号前的层级前缀 → sla_scope（009）；不认识的前缀记 other（前端注「scope in source table」），无前缀为 None
SCOPES = {"接入层": "access", "汇聚层": "aggregation", "主干层": "backbone", "骨干层": "backbone"}


@dataclass
class SlaDuration:
    value: Decimal  # 上限（范围取上限）
    value_min: Optional[Decimal]  # 范围的下限；单个值为 None
    unit: str
    scope: Optional[str] = None  # access / aggregation / backbone / other；无前缀为 None


def parse_duration(text: Optional[str]) -> Optional[SlaDuration]:
    """「2工作日」「1-2天」「≤3天内」「接入层：1吨/天」→ 数值 + 单位（+ 层级）；认不出的写法返回 None（不报错，原文另存）。"""
    if not text:
        return None
    s = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).lower().replace("～", "~").replace("–", "-")
    parts = s.split(":")  # NFKC 已把全角冒号变成半角
    if len(parts) > 2:
        return None  # 两个以上冒号：写法不明，不猜（审查 L-1）
    scope = None
    if len(parts) == 2:
        prefix, s = parts
        scope = SCOPES.get(prefix, "other")
    if len(s) == 2 and s[0] in CN_DIGITS:  # 「两周」「三天」：只认单个汉字数字
        s = CN_DIGITS[s[0]] + s[1]
    m = RATE_RE.match(s)
    if m:
        return SlaDuration(Decimal(m.group(1)), None, "tonne_per_day", scope)
    m = DURATION_RE.match(s)
    if not m:
        return None
    low, high, unit = m.group(1), m.group(2), UNIT_WORDS[m.group(3)]
    if high is None:
        return SlaDuration(Decimal(low), None, unit, scope)
    if Decimal(low) > Decimal(high):
        return None  # 「3-1天」：写反了，不猜
    return SlaDuration(Decimal(high), Decimal(low), unit, scope)


class SlaError(Exception):
    """模板文件不对（模板名不认识、缺表头、责任方不认识、节点号不对）。消息不含单元格内容。"""


@dataclass
class SlaStep:
    seq: int
    step: str
    owner: str
    sla_text: Any  # Optional[str]：表里没写 SLA 时长的节点为 None
    duration: Optional[SlaDuration] = None  # sla_text 解析不了或为空时为 None


@dataclass
class SlaTemplate:
    template: str
    steps: List[SlaStep]

    @property
    def unparsed(self) -> int:
        """写了时长原文却解析不了的节点数（没写时长的不算）。"""
        return sum(1 for s in self.steps if s.sla_text and s.duration is None)


def template_name(path: Path) -> str:
    m = NAME_RE.match(path.name)
    wanted = {t.lower(): t for t in TEMPLATES}
    if not m or m.group(1).lower() not in wanted:
        raise SlaError("file name must be DEPOSE-<%s>.xlsx" % "|".join(TEMPLATES))
    return wanted[m.group(1).lower()]


def _text(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _seq(v: Any, row_no: int) -> int:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or int(v) != v or v < 1:
        raise SlaError("row %d: %s is not a positive whole number" % (row_no, COL_SEQ))
    return int(v)


def parse_template(path: Path) -> SlaTemplate:
    name = template_name(path)
    rows = read_first_sheet(path)
    header = [_text(c) for c in rows[0]] if rows else []
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise SlaError("%s: missing column(s): %s" % (name, ", ".join(missing)))
    idx: Dict[str, int] = {c: header.index(c) for c in REQUIRED}
    steps: List[SlaStep] = []
    for n, row in enumerate(rows[1:], start=2):
        cell = [row[idx[c]] if idx[c] < len(row) else None for c in REQUIRED]
        if all(_text(c) == "" for c in cell):
            continue  # 表尾空行
        seq = _seq(cell[0], n)
        step = _text(cell[1])
        if not step:
            raise SlaError("row %d: %s is empty" % (n, COL_STEP))
        owner = OWNERS.get(_text(cell[3]))
        if owner is None:
            raise SlaError("row %d: unknown %s (expected one of the three known parties)" % (n, COL_OWNER))
        sla_text = _text(cell[2]) or None
        steps.append(SlaStep(seq, step, owner, sla_text, parse_duration(sla_text)))
    if not steps:
        raise SlaError("%s: no steps" % name)
    seqs = [s.seq for s in steps]
    if len(set(seqs)) != len(seqs):
        raise SlaError("%s: duplicate %s" % (name, COL_SEQ))
    steps.sort(key=lambda s: s.seq)
    return SlaTemplate(name, steps)


def _row(template: str, s: SlaStep) -> List[Any]:
    d = s.duration
    return [template, s.seq, s.step, s.owner, s.sla_text,
            d.value if d else None, d.value_min if d else None, d.unit if d else None, d.scope if d else None]


async def apply_templates(pool: Any, templates: Sequence[SlaTemplate], dry_run: bool = False) -> None:
    """一个事务内逐模板先删后插（本次没出现的模板不动）；失败整批回滚并抛出；dry_run 写完即回滚。"""
    names = [t.template for t in templates]
    if len(set(names)) != len(names):
        raise SlaError("the same template given twice")
    async with pool.acquire() as conn:
        tr = conn.transaction()
        await tr.start()
        try:
            for t in templates:
                await conn.execute("DELETE FROM sla_template_step WHERE template = $1", t.template)
                await conn.executemany(
                    "INSERT INTO sla_template_step (template, seq, step, owner, sla_text, sla_value, sla_value_min, sla_unit, sla_scope) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)",
                    [_row(t.template, s) for s in t.steps])
        except BaseException:
            await tr.rollback()
            raise
        if dry_run:
            await tr.rollback()
        else:
            await tr.commit()
    log.info("apply_templates dry_run=%s templates=%d", dry_run, len(templates))
    # 每模板一行计数，WARNING 级：import 命令把本模块日志压到 WARNING、走标准错误，运维（含 dry-run）能看到几个时长没解析出来
    # （前端对这些节点显示「—」）。只在事务成功后打，失败时标准错误仍以「error:」开头。只有计数，不带单元格内容。
    for t in templates:
        scopes = Counter(s.duration.scope for s in t.steps if s.duration and s.duration.scope)
        log.warning("%s: SLA durations parsed=%d unparsed=%d empty=%d scopes=%s", t.template, sum(1 for s in t.steps if s.duration),
                    t.unparsed, sum(1 for s in t.steps if not s.sla_text),
                    ",".join("%s:%d" % kv for kv in sorted(scopes.items())) or "none")
