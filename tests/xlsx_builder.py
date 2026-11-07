# risk: high
"""合成 xlsx 构造辅助（不是测试）：只用标准库 zipfile 拼 XML，不依赖 openpyxl，不含任何真实台账内容。

单元格值到 XML 的映射（与真实 Excel 导出对齐）：
  None            不写单元格（缺格）
  Blank()         带样式的空格 <c r=".." s="1"/>（Excel 常见）
  str             共享字符串 t="s"（含空串；首尾空白用 xml:space="preserve"）
  Rich(a, b)      共享字符串里的富文本多段 <r><t>
  Err("#N/A")     错误值 t="e"
  Formula(v, f)   <f> 加缓存 <v>；v 为 str 走 t="str"、为 Err 走 t="e"、为数字走默认
  bool            t="b"
  date            Excel 日期序号（1899-12-30 起算），数字单元格
  int / float     数字，float 用 repr 写出（44109.0 写成 "44109.0"）
  RawNum("1E-05") 原样写进 <v> 的数字文本
行：None 表示整行不写（行号照占，Excel 省略全空行的样子）；全 None 列表写成空 <row/>。
"""
import datetime
import zipfile
from xml.sax.saxutils import escape

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
EPOCH = datetime.date(1899, 12, 30)
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
DOCTYPE = '<!DOCTYPE x [<!ENTITY a "b">]>\n'


class Err(str):
    """错误值单元格，如 #N/A。"""


class RawNum(str):
    """原样写入 <v> 的数字文本，用来造科学计数法等写法。"""


class IsoDate(str):
    """t="d" 单元格（ISO 8601 文本，如 2026-11-25T00:00:00）。"""


class RawCell(object):
    """原样单元格：t 为 None 则不写 t 属性；v 原样（转义后）写进 <v>。用来造负数 / 越界共享串下标、乱码数字。"""

    def __init__(self, t, v):
        self.t = t
        self.v = v


class Blank(object):
    """没有值的单元格：styled=True 写成 <c r=".." s="1"/>（Excel 常见），False 写成 <c r=".."/>。"""

    def __init__(self, styled=True):
        self.styled = styled


class Formula(object):
    def __init__(self, value, f="SUM(A1:B1)"):
        self.value = value
        self.f = f


class Rich(object):
    def __init__(self, *parts):
        self.parts = parts


def col_letter(idx):
    """0 -> A, 25 -> Z, 26 -> AA, 27 -> AB。"""
    n = idx + 1
    out = ""
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def excel_serial(d):
    return (d - EPOCH).days


def _t(text):
    return '<t xml:space="preserve">%s</t>' % escape(text)


class _Sst(object):
    def __init__(self):
        self.items = []
        self.index = {}
        self.refs = 0

    def add(self, key, xml):
        self.refs += 1
        if key not in self.index:
            self.index[key] = len(self.items)
            self.items.append(xml)
        return self.index[key]


def _num(v):
    return repr(v) if isinstance(v, float) else str(v)


def _formula_cell(ref, fm):
    f = "<f>%s</f>" % escape(fm.f)
    val = fm.value
    if isinstance(val, Err):
        return '<c r="%s" t="e">%s<v>%s</v></c>' % (ref, f, escape(val))
    if isinstance(val, str):
        return '<c r="%s" t="str">%s<v>%s</v></c>' % (ref, f, escape(val))
    if isinstance(val, bool):
        return '<c r="%s" t="b">%s<v>%d</v></c>' % (ref, f, int(val))
    return '<c r="%s">%s<v>%s</v></c>' % (ref, f, _num(val))


def _cell(ref, v, sst):
    if v is None:
        return ""
    if isinstance(v, Blank):
        return ('<c r="%s" s="1"/>' if v.styled else '<c r="%s"/>') % ref
    if isinstance(v, IsoDate):
        return '<c r="%s" t="d"><v>%s</v></c>' % (ref, escape(v))
    if isinstance(v, RawCell):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, (' t="%s"' % v.t) if v.t else "", escape(v.v))
    if isinstance(v, Formula):
        return _formula_cell(ref, v)
    if isinstance(v, Err):
        return '<c r="%s" t="e"><v>%s</v></c>' % (ref, escape(v))
    if isinstance(v, RawNum):
        return '<c r="%s"><v>%s</v></c>' % (ref, escape(v))
    if isinstance(v, Rich):
        idx = sst.add(("r", v.parts), "<si>%s</si>" % "".join("<r>%s</r>" % _t(p) for p in v.parts))
        return '<c r="%s" t="s"><v>%d</v></c>' % (ref, idx)
    if isinstance(v, str):
        idx = sst.add(("s", v), "<si>%s</si>" % _t(v))
        return '<c r="%s" t="s"><v>%d</v></c>' % (ref, idx)
    if isinstance(v, bool):
        return '<c r="%s" t="b"><v>%d</v></c>' % (ref, int(v))
    if isinstance(v, datetime.date):
        return '<c r="%s" s="2"><v>%d</v></c>' % (ref, excel_serial(v))
    if isinstance(v, (int, float)):
        return '<c r="%s"><v>%s</v></c>' % (ref, _num(v))
    raise TypeError("builder cannot encode %r" % (v,))


def _sheet_xml(rows, sst, pad):
    parts = [XML_DECL, '<worksheet xmlns="%s"><sheetData>' % NS_MAIN]
    if pad:
        parts.append(" " * pad)
    for n, row in enumerate(rows, start=1):
        if row is None:
            continue
        items = sorted(row.items()) if isinstance(row, dict) else enumerate(row)  # dict 行：{列位置: 值}，造远列格不必铺 16384 个 None
        cells = "".join(_cell("%s%d" % (col_letter(i), n), v, sst) for i, v in items)
        parts.append('<row r="%d">%s</row>' % (n, cells) if cells else '<row r="%d"/>' % n)
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def build_xlsx(path, rows, second_sheet_rows=None, first_sheet_in_sheet2=False,
               no_sheets=False, sheet_pad=0, shared_pad=0, doctype_in=(), stored=False):
    """拼一个 xlsx 写到 path，返回 str(path)。

    second_sheet_rows      再加一个工作表（用来验证只读第一个）
    first_sheet_in_sheet2  workbook.xml 里的第一个工作表物理上存在 worksheets/sheet2.xml，
                           sheet1.xml 放第二个工作表——只认 sheet1.xml 的读取器会读到别的表
    no_sheets              workbook.xml 里一个 <sheet> 都没有
    sheet_pad / shared_pad 往第一个工作表 / sharedStrings.xml 里塞这么多字节的空白（压缩后很小，
                           解压后很大，用来造「压缩炸弹」形状的成员）
    doctype_in             在哪些 XML 成员里注入 <!DOCTYPE ...>："sheet"（第一个工作表）/ "shared" / "workbook"
    stored                 True 则 zip 不压缩（XML 明文在文件里，随机翻字节能打到 XML 文本本身）
    """
    sst = _Sst()
    sheets = [("Ledger", rows)]
    if second_sheet_rows is not None:
        sheets.append(("Other", second_sheet_rows))
    files = ["worksheets/sheet%d.xml" % (i + 1) for i in range(len(sheets))]
    if first_sheet_in_sheet2 and len(files) == 2:
        files.reverse()
    sheet_xml = {}
    if not no_sheets:
        for i, ((_, rws), fn) in enumerate(zip(sheets, files)):
            sheet_xml[fn] = _sheet_xml(rws, sst, sheet_pad if i == 0 else 0)

    sheet_tags = "".join('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (name, i + 1, i + 1)
                         for i, (name, _) in enumerate(sheets)) if not no_sheets else ""
    workbook = (XML_DECL + '<workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>'
                % (NS_MAIN, NS_REL, sheet_tags))
    rels = ""
    if not no_sheets:
        rels = "".join('<Relationship Id="rId%d" Type="%s/worksheet" Target="%s"/>'
                       % (i + 1, NS_REL, fn) for i, fn in enumerate(files))
    if sst.items:
        rels += '<Relationship Id="rId99" Type="%s/sharedStrings" Target="sharedStrings.xml"/>' % NS_REL
    wb_rels = XML_DECL + '<Relationships xmlns="%s">%s</Relationships>' % (NS_PKG_REL, rels)

    def dt(xml, on):
        return xml.replace(XML_DECL, XML_DECL + DOCTYPE, 1) if on else xml

    if "shared" in doctype_in and not sst.items:
        raise ValueError("doctype_in='shared' needs at least one string cell")
    with zipfile.ZipFile(str(path), "w", zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED,
                         compresslevel=1) as zf:
        zf.writestr("[Content_Types].xml", XML_DECL + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        zf.writestr("_rels/.rels", XML_DECL + '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%s/officeDocument" Target="xl/workbook.xml"/></Relationships>' % (NS_PKG_REL, NS_REL))
        zf.writestr("xl/workbook.xml", dt(workbook, "workbook" in doctype_in))
        zf.writestr("xl/_rels/workbook.xml.rels", wb_rels)
        for fn, xml in sheet_xml.items():
            zf.writestr("xl/" + fn, dt(xml, "sheet" in doctype_in and fn == files[0]))
        if sst.items:
            zf.writestr("xl/sharedStrings.xml", dt(XML_DECL + '<sst xmlns="%s" count="%d" uniqueCount="%d">%s%s</sst>'
                        % (NS_MAIN, sst.refs, len(sst.items), " " * shared_pad, "".join(sst.items)),
                        "shared" in doctype_in))
    return str(path)


# ---------------------------------------------------------------- 台账（合成表头，复刻真表的怪处）

# 真实表头顺序：重名（Category / Min Weight / Weight(T) / Maximum Weight / Executed Weight 各两次）、
# 拼写错误（Recieve date / Length9(km)）原样保留。
HEADERS = ["UCI", "Seq", "Subcon", "Site Ville", "Commun", "POI", "Category", "Status",
           "Total Avg. Weight", "Executed Weight", "Retassage", "Executed Pairs", "Category", "Cable",
           "type infrastructure", "Length9(km)", "Min Weight", "Weight(T)", "Maximum Weight",
           "Executed Weight", "Recieve date", "Planned Operation Date", "Avg. Min", "Avg (T/KM)",
           "Avg.Max", "Min Weight", "Weight(T)", "Maximum Weight"]

# 友好名 -> 列位置（0 起）。min_1/max_1/executed_* 是第一组、会被忽略的重名列，测试里用来放「哨兵值」。
COLS = {"uci": 0, "seq": 1, "subcon": 2, "site_ville": 3, "commun": 4, "poi": 5, "category": 6,
        "status": 7, "total_avg": 8, "executed_1": 9, "retassage": 10, "executed_pairs": 11,
        "cable_category": 12, "cable": 13, "infra": 14, "length": 15, "min_1": 16, "weight": 17,
        "max_1": 18, "executed_2": 19, "received": 20, "planned": 21, "avg_min": 22, "avg_tkm": 23,
        "avg_max": 24, "ref_min": 25, "ref_avg": 26, "ref_max": 27}

assert len(HEADERS) == 28 and max(COLS.values()) == 27


def ledger_row(**kw):
    """按友好名填一行（其余为 None）；拼错名字直接 KeyError。"""
    row = [None] * len(HEADERS)
    for k, v in kw.items():
        row[COLS[k]] = v
    return row


def without_header(name):
    """把表头里所有叫 name 的列改名成占位名（列位置不变），用来造「缺列」。"""
    return ["zz_" + h if h == name else h for h in HEADERS]


def with_header(col, text):
    """只改某一列（友好名）的表头文字，用来造大小写 / 空白写法不同的表头。"""
    headers = list(HEADERS)
    headers[COLS[col]] = text
    return headers


def write_ledger(path, rows, headers=None, **kw):
    return build_xlsx(path, [list(headers or HEADERS)] + list(rows), **kw)
