"""只读极简 xlsx 读取器：只认第一个工作表的单元格值，不依赖 openpyxl（标准库 zipfile + ElementTree）。

读错单元格类型 = 台账数字整体偏，所以：类型按 <c t=..> 分、列位置以 r="AB12" 为准（行内可跳格）、
错误值返回 XlError（不会被当成数）、公式单元格取缓存 <v>。
元素一律按去掉命名空间的本地名匹配（真文件可能带 x: 之类前缀）。
"""
import importlib
import io
import logging
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
import zlib
from typing import Any, Dict, Iterator, List, Optional, Tuple

log = logging.getLogger(__name__)

MAX_XML_BYTES = 50 * 1024 * 1024  # 解压后单个 XML 成员上限，防压缩炸弹
MAX_CELLS = 2000000               # 整张表「有值」的单元格上限，防稀疏炸弹（无值的格不计、不扩表）
MAX_ROWS = 1048576                # Excel 行数上限，r 属性超出视为坏文件，免得按它补出海量空行
MAX_COLS = 16384                  # Excel 列数上限（XFD）
FALLBACK_SHEET = "xl/worksheets/sheet1.xml"
_REF_RE = re.compile(r"^([A-Za-z]{1,3})([0-9]+)$")
# 损坏文件在构造 ZipFile、读成员、解析 XML 时可能冒出的底层异常（坏 CRC / 坏压缩流 / 截断 / 不支持的压缩法 /
# 加密成员 / 文件名编码坏），一律转成 XlsxError；文件不存在不在其内，照常抛 FileNotFoundError
_READ_ERRORS = (ET.ParseError, zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError,
                OSError, ValueError, EOFError)
# zip 还支持 lzma 压缩，3.14+ 还支持 zstd，它们的坏流各抛自己的异常类型；模块不在（旧版本 / 没编译）就不加
for _mod, _name in (("lzma", "LZMAError"), ("compression.zstd", "ZstdError")):
    try:
        _READ_ERRORS += (getattr(importlib.import_module(_mod), _name),)
    except ImportError:
        pass


class XlsxError(Exception):
    """文件不是可读的 xlsx（不是 zip、没有工作表、XML 坏了或超限）。"""


class XlError(str):
    """Excel 错误值单元格（#N/A、#DIV/0! 等）；是 str 子类，但绝不是数。"""


def _local(name: str) -> str:
    """去掉 {namespace} 前缀，只留本地名。"""
    return name.rsplit("}", 1)[-1]


def _member(zf: zipfile.ZipFile, name: str) -> Optional[zipfile.ZipInfo]:
    """取 zip 成员信息；不存在返回 None。超限先按头里的 file_size 拒绝，不解压。"""
    try:
        info = zf.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_XML_BYTES:
        raise XlsxError("%s is %d bytes uncompressed, over the %d byte limit"
                        % (name, info.file_size, MAX_XML_BYTES))
    return info


def _load(zf: zipfile.ZipFile, name: str) -> Optional[bytes]:
    """读出一个 XML 成员的字节（已按头里的 file_size 限过 50 MB）；不存在返回 None。

    先在字节里找 <!DOCTYPE 再交给解析器：xlsx 不需要 DTD，有 DTD 就是实体膨胀之类攻击的入口，直接拒。
    """
    info = _member(zf, name)
    if info is None:
        return None
    try:
        with zf.open(info) as fh:
            data = fh.read()
    except _READ_ERRORS as exc:
        raise XlsxError("cannot read %s: %s" % (name, exc)) from exc
    if b"<!DOCTYPE" in data:
        raise XlsxError("%s contains a DOCTYPE declaration, refused" % name)
    return data


def _read_root(zf: zipfile.ZipFile, name: str) -> Optional[ET.Element]:
    data = _load(zf, name)
    if data is None:
        return None
    try:
        return ET.fromstring(data)
    except _READ_ERRORS as exc:
        raise XlsxError("cannot read %s: %s" % (name, exc)) from exc


def _iter_end(data: bytes, name: str) -> Iterator[ET.Element]:
    """流式解析大 XML，逐个吐出结束的元素；调用方用完要 clear()，树不随文件线性涨。"""
    try:
        for _event, el in ET.iterparse(io.BytesIO(data), events=("end",)):
            yield el
    except _READ_ERRORS as exc:
        raise XlsxError("cannot read %s: %s" % (name, exc)) from exc


def _resolve(target: str) -> str:
    """关系 Target 转成 zip 内路径：绝对路径从包根起，相对路径相对 xl/。"""
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    return posixpath.normpath(posixpath.join("xl", target))


def _relationships(zf: zipfile.ZipFile) -> List[Dict[str, str]]:
    root = _read_root(zf, "xl/_rels/workbook.xml.rels")
    if root is None:
        return []
    return [dict(el.attrib) for el in root.iter() if _local(el.tag) == "Relationship"]


def _first_sheet_path(zf: zipfile.ZipFile, rels: List[Dict[str, str]]) -> str:
    """workbook.xml 第一个 <sheet> 的 r:id 经 rels 找路径；找不到退回 sheet1.xml（记一条警告），再没有就抛。"""
    wb = _read_root(zf, "xl/workbook.xml")
    rid = None
    if wb is not None:
        for el in wb.iter():
            if _local(el.tag) == "sheet":
                # r:id 的前缀 / 命名空间不固定，按本地名 id 取（sheetId 的本地名是 sheetId，不会误中）
                rid = next((v for k, v in el.attrib.items() if _local(k) == "id"), None)
                break
    path = None
    for rel in rels:
        if rid is not None and rel.get("Id") == rid:
            path = _resolve(rel.get("Target", ""))
            break
    if path is not None and path in zf.namelist():
        return path
    if FALLBACK_SHEET not in zf.namelist():
        raise XlsxError("no worksheet found in workbook")
    log.warning("first sheet not resolvable via workbook.xml, falling back to %s", FALLBACK_SHEET)
    return FALLBACK_SHEET


def _rich_text(si: ET.Element) -> str:
    """共享字符串条目 / 内联字符串的文本：直接的 <t> 加各 <r> 里的 <t> 拼接；<rPh> 拼音注释不算。"""
    parts: List[str] = []
    for child in si:
        name = _local(child.tag)
        if name == "t":
            parts.append(child.text or "")
        elif name == "r":
            parts.extend(t.text or "" for t in child if _local(t.tag) == "t")
    return "".join(parts)


def _shared_strings(zf: zipfile.ZipFile, rels: List[Dict[str, str]]) -> List[str]:
    name = "xl/sharedStrings.xml"
    for rel in rels:
        if rel.get("Type", "").endswith("/sharedStrings"):
            name = _resolve(rel.get("Target", ""))
    data = _load(zf, name)
    if data is None:
        return []
    out: List[str] = []
    for el in _iter_end(data, name):
        if _local(el.tag) == "si":
            out.append(_rich_text(el))
            el.clear()
    return out


def _col_index(ref: str) -> int:
    m = _REF_RE.match(ref)
    if not m:
        raise XlsxError("bad cell reference %r" % ref)
    n = 0
    for ch in m.group(1).upper():
        n = n * 26 + ord(ch) - 64
    if n > MAX_COLS:
        raise XlsxError("cell reference %s is beyond column %d" % (ref, MAX_COLS))
    return n - 1


def _number(text: str, ref: str) -> Any:
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        raise XlsxError("cell %s holds a non-numeric value in a numeric cell" % ref) from None


def _cell_value(c: ET.Element, sst: List[str], ref: str) -> Any:
    t = c.get("t")
    v = inline = None
    for child in c:
        name = _local(child.tag)
        if name == "v":
            v = child
        elif name == "is":
            inline = child
    if t == "inlineStr":
        return _rich_text(inline) if inline is not None else None
    if v is None:  # 带样式的空格，或有公式没缓存值
        return None
    text = v.text or ""
    if t == "s":
        if not text:
            return None
        try:
            idx = int(text)
            if idx < 0:  # 负下标会按 Python 习惯读成倒数第几条，必须拒
                raise IndexError(idx)
            return sst[idx]
        except (ValueError, IndexError):
            raise XlsxError("cell %s points at a shared string that does not exist" % ref) from None
    if t in ("str", "d"):  # 公式的字符串结果；t="d" 是 ISO 8601 日期文本，原样给调用方（xlsx_min 不解释日期）
        return text
    if t == "e":
        return XlError(text)
    if t == "b":
        return text.strip() == "1"
    if t in (None, "n"):
        return _number(text, ref) if text.strip() else None
    raise XlsxError("cell %s has unsupported type %r" % (ref, t))


def _row_cells(row: ET.Element, sst: List[str]) -> Tuple[List[Any], int]:
    """-> (这一行的值列表, 有值的格数)。无值的格（无 <v>、无内联串：带样式的空格、没缓存值的公式）不扩表，
    行长度只到有值的最大列——否则一个 XFD 列的空格就能把每行撑到 16384 个 None。"""
    cells: List[Any] = []
    valued = 0
    col = -1
    for c in row:
        if _local(c.tag) != "c":
            continue
        ref = c.get("r")
        col = _col_index(ref) if ref else col + 1  # r 缺省时按顺序往后排
        if col >= MAX_COLS:
            raise XlsxError("row has more than %d cells" % MAX_COLS)
        if not any(_local(ch.tag) in ("v", "is") for ch in c):
            continue
        valued += 1
        value = _cell_value(c, sst, ref or "#%d" % (col + 1))
        if len(cells) <= col:
            cells.extend([None] * (col + 1 - len(cells)))
        cells[col] = value
    return cells, valued


def _read_rows(data: bytes, name: str, sst: List[str]) -> List[List[Any]]:
    rows: List[List[Any]] = []  # 下标 = 行号 - 1；Excel 省略的整行补 []，行号才对得上（报错里的行号就是 Excel 行号）
    total = 0
    for el in _iter_end(data, name):
        if _local(el.tag) != "row":
            continue
        raw_no = el.get("r")
        try:
            number = int(raw_no) if raw_no else len(rows) + 1
        except ValueError:
            raise XlsxError("bad row number %r" % raw_no) from None
        if number > MAX_ROWS:
            raise XlsxError("row number %d is beyond Excel's limit %d" % (number, MAX_ROWS))
        if number <= len(rows):
            raise XlsxError("row %d appears out of order" % number)
        rows.extend([] for _ in range(number - 1 - len(rows)))
        cells, valued = _row_cells(el, sst)
        total += valued
        if total > MAX_CELLS:
            raise XlsxError("sheet has more than %d cells with values" % MAX_CELLS)
        rows.append(cells)
        el.clear()
    while rows and all(v is None for v in rows[-1]):  # 尾部的空行（只有样式）不算数据
        rows.pop()
    return rows


def read_first_sheet(path: Any) -> List[List[Any]]:
    """读 xlsx 第一个工作表，返回按行号对齐的二维列表（缺格 None，缺行 []）。

    损坏 / 不是 zip / 没有工作表 / XML 坏 / 含 DOCTYPE / 成员超 50 MB / 有值格超 MAX_CELLS 一律抛 XlsxError；
    文件不存在或没权限照常抛 OSError（FileNotFoundError），不当成「文件损坏」。
    """
    open(path, "rb").close()  # 先单独打开一次：路径问题原样抛出，后面的 OSError 才都是文件内容的问题
    try:
        zf = zipfile.ZipFile(path)
    except _READ_ERRORS as exc:
        raise XlsxError("not a valid xlsx file: %s" % exc) from exc
    with zf:
        try:
            rels = _relationships(zf)
            sheet_path = _first_sheet_path(zf, rels)
            data = _load(zf, sheet_path)
            if data is None:
                raise XlsxError("no worksheet found in workbook")
            return _read_rows(data, sheet_path, _shared_strings(zf, rels))
        except _READ_ERRORS as exc:  # zf.namelist() / getinfo 等没单独包的读取点兜底
            raise XlsxError("cannot read xlsx: %s" % exc) from exc
