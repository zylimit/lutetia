"""`lutetia import poi FILE [--dry-run]`：读台账 → 汇总打印 → 入库；`lutetia import sla FILE… [--dry-run]` 见文件末。

顺序是契约：解析与 0 单检查都在任何连库动作之前，台账有问题时不连库、库不动。
标准输出只有固定的汇总行；除可疑工单号外不打印任何行内容（台账是真实业务数据）。
"""
import asyncio
import logging
import sys
from pathlib import Path

import asyncpg

from .config import Config
from .db import Database, DatabaseConnectError
from .poi_import import LedgerError, LedgerParse, parse_ledger
from .poi_store import apply_ledger
from .sla_import import SlaError, apply_templates, parse_template
from .xlsx_min import XlsxError


def _fail(msg: str) -> int:
    print("error: %s" % msg, file=sys.stderr)
    return 1


def _read(path: Path) -> LedgerParse:
    if not path.is_file():
        raise FileNotFoundError(path)
    return parse_ledger(path)


def _logs_to_stderr() -> None:
    """本命令内日志改走标准错误：标准输出只留固定汇总行（不改 log.py 的全局行为，collector 仍写标准输出）。"""
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout:
            h.setStream(sys.stderr)


async def cmd_import_poi(cfg: Config, args) -> int:
    _logs_to_stderr()
    path = Path(args.file)
    try:
        parsed = _read(path)
    except FileNotFoundError:
        return _fail("file not found: %s" % path)
    except (LedgerError, XlsxError) as e:
        return _fail(str(e))
    except OSError as e:
        return _fail("cannot read %s: %s" % (path, e.strerror or e))
    if not parsed.pois:
        return _fail("no POI rows in ledger")
    if not cfg.database_url:
        return _fail("missing configuration: DATABASE_URL")
    # apply_ledger 会 log.info 一行计数；日志默认写标准输出，会混进固定格式的汇总，所以只在本命令里把这个 logger 提到 WARNING
    logging.getLogger("lutetia.poi_store").setLevel(logging.WARNING)
    db = Database(cfg.database_url)
    try:
        await db.connect()
        try:
            res = await apply_ledger(db.pool, parsed.pois, dry_run=args.dry_run)
        finally:
            await db.close()
    except (OSError, asyncio.TimeoutError, asyncpg.PostgresError, asyncpg.InterfaceError) as e:
        # 只报异常类名：异常文本可能带行内容（台账是真实业务数据）；apply_ledger 单事务，失败即整批回滚
        reason = str(e) if isinstance(e, DatabaseConnectError) else type(e).__name__  # DatabaseConnectError 的文本只含原因类名，安全
        return _fail("database: %s (nothing written)" % reason)
    if args.dry_run:
        print("dry-run: nothing written")
    print("read: %d POI / %d segments (%d POI without cable detail)"
          % (len(parsed.pois), parsed.segment_count, parsed.pois_without_segments))
    print("result: %d new, %d updated, %d unchanged, %d raw refreshed, %d gone from ledger"
          % (res["new"], res["updated"], res["unchanged"], res["raw_refreshed"], res["gone"]))
    c = parsed.cleaned
    print("cleaned: uci_normalised=%d trimmed_cells=%d na_to_empty=%d segment_no_cable_type=%d not_a_number=%d; "
          "occ_unparsed=%d" % (c["uci_normalised"], c["trimmed_cells"], c["na_to_empty"],
                               c["segment_no_cable_type"], c["not_a_number"], parsed.occ_unparsed))
    print("suspicious: %s" % (", ".join(parsed.suspicious) if parsed.suspicious else "none"))
    return 0


async def cmd_import_sla(cfg: Config, args) -> int:
    """`lutetia import sla FILE [FILE…] [--dry-run]`：同样先解析再连库；输出只有「模板名 + 步数」，不打任何单元格内容。"""
    _logs_to_stderr()
    templates = []
    for f in args.files:
        path = Path(f)
        try:
            if not path.is_file():
                raise FileNotFoundError(path)
            templates.append(parse_template(path))
        except FileNotFoundError:
            return _fail("file not found: %s" % path)
        except (SlaError, XlsxError) as e:
            return _fail("%s: %s" % (path.name, e))
        except OSError as e:
            return _fail("cannot read %s: %s" % (path, e.strerror or e))
    if not cfg.database_url:
        return _fail("missing configuration: DATABASE_URL")
    logging.getLogger("lutetia.sla_import").setLevel(logging.WARNING)
    db = Database(cfg.database_url)
    try:
        await db.connect()
        try:
            await apply_templates(db.pool, templates, dry_run=args.dry_run)
        finally:
            await db.close()
    except SlaError as e:
        return _fail(str(e))
    except (OSError, asyncio.TimeoutError, asyncpg.PostgresError, asyncpg.InterfaceError) as e:
        reason = str(e) if isinstance(e, DatabaseConnectError) else type(e).__name__
        return _fail("database: %s (nothing written)" % reason)
    if args.dry_run:
        print("dry-run: nothing written")
    for t in templates:
        print("%s: %d steps" % (t.template, len(t.steps)))
    return 0
