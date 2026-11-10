"""SLA 流程模板导入：DEPOSE-Transportation / Distribution / MASSIVE 三份 xlsx → sla_template_step。
按表头名取列（Number* / Name* / SLA典型时长 / Responsible party*），第一个工作表。模板名取自文件名（DEPOSE-<模板>.xlsx）。
纯解析 + 一个事务的整模板替换；错误信息和日志只带行号与列名，不带单元格内容（SLA 表只在欧洲境内的库里）。
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence

from .xlsx_min import read_first_sheet

log = logging.getLogger(__name__)

TEMPLATES = ("Transportation", "Distribution", "MASSIVE")
# 表头名是 DEPOSE 表的原样写法（含星号与中文），不是笔误
COL_SEQ, COL_STEP, COL_SLA, COL_OWNER = "Number*", "Name*", "SLA典型时长", "Responsible party*"
REQUIRED = [COL_SEQ, COL_STEP, COL_SLA, COL_OWNER]
OWNERS = {"客户": "customer", "华为": "huawei", "合作方": "partner"}
NAME_RE = re.compile(r"^DEPOSE-(.+)\.xlsx$", re.IGNORECASE)


class SlaError(Exception):
    """模板文件不对（模板名不认识、缺表头、责任方不认识、节点号不对）。消息不含单元格内容。"""


@dataclass
class SlaStep:
    seq: int
    step: str
    owner: str
    sla_text: Any  # Optional[str]：表里没写 SLA 时长的节点为 None


@dataclass
class SlaTemplate:
    template: str
    steps: List[SlaStep]


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
        steps.append(SlaStep(seq, step, owner, _text(cell[2]) or None))
    if not steps:
        raise SlaError("%s: no steps" % name)
    seqs = [s.seq for s in steps]
    if len(set(seqs)) != len(seqs):
        raise SlaError("%s: duplicate %s" % (name, COL_SEQ))
    steps.sort(key=lambda s: s.seq)
    return SlaTemplate(name, steps)


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
                    "INSERT INTO sla_template_step (template, seq, step, owner, sla_text) VALUES ($1, $2, $3, $4, $5)",
                    [[t.template, s.seq, s.step, s.owner, s.sla_text] for s in t.steps])
        except BaseException:
            await tr.rollback()
            raise
        if dry_run:
            await tr.rollback()
        else:
            await tr.commit()
    log.info("apply_templates dry_run=%s templates=%d", dry_run, len(templates))
