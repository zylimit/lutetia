# risk: high
"""lutetia.xlsx_min：只读极简 xlsx 读取器（Task 5.1，SCOPE-16 前半）。
断言来自 DEV-PLAN Task 5.1 的接口约定与派单书，不看实现。xlsx 一律用 tests/xlsx_builder.py 拼的合成文件。
读错单元格类型 = 台账数字整体偏，所以单元格类型、缺格对位、XlError 不当数值、第一个工作表、50 MB 上限都在这里钉死。"""
import os
import pathlib
import random
import zipfile

import pytest

import lutetia.xlsx_min as xlsx_mod
from lutetia.xlsx_min import XlError, XlsxError, read_first_sheet
from xlsx_builder import Blank, Err, Formula, IsoDate, RawCell, RawNum, Rich, build_xlsx


def xl(tmp_path, rows, **kw):
    return build_xlsx(tmp_path / "t.xlsx", rows, **kw)


# risk: high
def test_cell_types_text_number_bool_formula_error(tmp_path):
    rows = [["text", 7, 2.064, -3, RawNum("1E-05"), True, False,
             Formula(5, "A1+B1"), Formula("abc", 'A1&"x"'), Err("#N/A"), Formula(2.5, "X1*2")]]
    got = read_first_sheet(xl(tmp_path, rows))
    assert len(got) == 1
    r = got[0]
    assert r[0] == "text" and type(r[0]) is str
    assert r[1] == 7 and type(r[1]) in (int, float)
    assert r[2] == 2.064 and isinstance(r[2], float)
    assert r[3] == -3 and type(r[3]) in (int, float)
    assert isinstance(r[4], float) and r[4] == 1e-05
    assert r[5] is True and r[6] is False
    # 公式单元格取缓存值（数字、字符串）
    assert r[7] == 5 and type(r[7]) in (int, float)
    assert r[8] == "abc" and type(r[8]) is str
    assert isinstance(r[9], XlError) and r[9] == "#N/A"
    assert r[10] == 2.5


# risk: high
def test_error_values_are_xlerror_never_numbers(tmp_path):
    texts = ["#N/A", "#DIV/0!", "#REF!", "#VALUE!", "#NAME?", "#NULL!", "#NUM!"]
    got = read_first_sheet(xl(tmp_path, [[Err(t) for t in texts]]))[0]
    assert issubclass(XlError, str)
    for cell, text in zip(got, texts):
        assert isinstance(cell, XlError)
        assert isinstance(cell, str) and cell == text
        assert not isinstance(cell, (int, float))


# risk: high
def test_formula_cell_with_error_cache_is_xlerror(tmp_path):
    # 真表里参考重量是外链公式，缓存值就是 #N/A：<c t="e"><f>..</f><v>#N/A</v></c>
    got = read_first_sheet(xl(tmp_path, [[Formula(Err("#N/A"), "VLOOKUP(A1,[1]Sheet1!$A:$B,2,0)"), 1.5]]))[0]
    assert isinstance(got[0], XlError) and got[0] == "#N/A"
    assert got[1] == 1.5


# risk: high
def test_shared_strings_keep_whitespace_escapes_and_unicode(tmp_path):
    vals = ["AURA ", "  lead", "a  b", "A & B <x> \"q\"", "Saint-Étienne ¤", "l1\nl2", "AURA ", ""]
    got = read_first_sheet(xl(tmp_path, [vals]))[0]
    # 读取器不清洗：尾空格、内部连续空格原样还原（清洗归 poi_import）；重复字符串各格都还原
    assert got[:7] == vals[:7]
    assert got[7] in ("", None)


# risk: medium
def test_shared_string_rich_text_runs_are_concatenated(tmp_path):
    got = read_first_sheet(xl(tmp_path, [[Rich("Foo", " bar ", "baz"), "plain"]]))[0]
    assert got == ["Foo bar baz", "plain"]


# risk: high
def test_missing_cells_are_padded_by_column_position(tmp_path):
    rows = [["a", None, "c", Blank(), "e"],
            [None, "b"],
            [None] * 26 + ["AA-cell", "AB-cell"]]
    got = read_first_sheet(xl(tmp_path, rows))
    assert got[0][:5] == ["a", None, "c", None, "e"]
    assert got[1][:2] == [None, "b"]
    assert got[2][26] == "AA-cell" and got[2][27] == "AB-cell"
    assert all(v is None for v in got[2][:26])


# risk: medium
def test_numbers_only_workbook_without_shared_strings_part(tmp_path):
    path = xl(tmp_path, [[1, 2.5], [3, 4]])
    with zipfile.ZipFile(path) as zf:
        assert "xl/sharedStrings.xml" not in zf.namelist()
    assert read_first_sheet(path) == [[1, 2.5], [3, 4]]


# risk: high
def test_reads_the_first_sheet_in_workbook_order(tmp_path):
    p1 = build_xlsx(tmp_path / "a.xlsx", [["first", 1]], second_sheet_rows=[["second", 2]])
    assert read_first_sheet(p1) == [["first", 1]]
    # workbook.xml 里排第一的表物理上在 worksheets/sheet2.xml，sheet1.xml 是别的表
    p2 = build_xlsx(tmp_path / "b.xlsx", [["real", 1]], second_sheet_rows=[["decoy", 2]],
                    first_sheet_in_sheet2=True)
    assert read_first_sheet(p2) == [["real", 1]]


# risk: low
def test_accepts_pathlib_path(tmp_path):
    path = xl(tmp_path, [["x", 1]])
    assert read_first_sheet(pathlib.Path(path)) == [["x", 1]]


# risk: high
def test_not_a_zip_raises_xlsxerror(tmp_path):
    bad = tmp_path / "bad.xlsx"
    bad.write_bytes(b"this is not a zip archive")
    with pytest.raises(XlsxError):
        read_first_sheet(str(bad))
    empty = tmp_path / "empty.xlsx"
    empty.write_bytes(b"")
    with pytest.raises(XlsxError):
        read_first_sheet(str(empty))


# risk: high
def test_zip_without_worksheet_raises_xlsxerror(tmp_path):
    with pytest.raises(XlsxError):
        read_first_sheet(xl(tmp_path, [["x"]], no_sheets=True))
    other = tmp_path / "other.zip"
    with zipfile.ZipFile(str(other), "w") as zf:
        zf.writestr("hello.txt", "not a workbook")
    with pytest.raises(XlsxError):
        read_first_sheet(str(other))


# risk: high
@pytest.mark.parametrize("where", ["sheet", "shared_strings"])
def test_xml_member_over_50mb_uncompressed_is_refused(tmp_path, where):
    over = 51 * 1024 * 1024  # 既大于 50 MiB 也大于 50 MB，两种口径都算超
    kw = {"sheet_pad": over} if where == "sheet" else {"shared_pad": over}
    path = xl(tmp_path, [["a", 1]], **kw)
    assert os.path.getsize(path) < 5 * 1024 * 1024  # 压缩炸弹形状：文件小、解压大
    with pytest.raises(XlsxError):
        read_first_sheet(path)


# risk: medium
def test_large_but_legit_member_is_not_refused(tmp_path):
    path = xl(tmp_path, [["a", 1]], sheet_pad=30 * 1000 * 1000)  # 30 MB 空白，低于任何口径的 50 MB
    assert read_first_sheet(path) == [["a", 1]]


# ------------------------------------------------------------------ 审查修复：M-1 / M-2 / L-4 / L-5

# risk: high
def test_max_cells_is_a_module_constant_and_caps_valued_cells(tmp_path, monkeypatch):
    assert xlsx_mod.MAX_CELLS == 2000000
    big = build_xlsx(tmp_path / "big.xlsx", [list(range(10)) for _ in range(6)])  # 60 个有值格
    small = build_xlsx(tmp_path / "small.xlsx", [list(range(10)) for _ in range(4)])  # 40 个有值格
    monkeypatch.setattr(xlsx_mod, "MAX_CELLS", 50)
    with pytest.raises(XlsxError):
        read_first_sheet(big)
    assert len(read_first_sheet(small)) == 4  # 没超就照读


# risk: high
def test_empty_far_column_cells_do_not_expand_the_row(tmp_path):
    # 2000 行、每行只有一个空的 XFDn 格（一半带样式一半不带）：每行长度不得被撑到 16384
    rows = [{16383: Blank(styled=(i % 2 == 0))} for i in range(2000)]
    got = read_first_sheet(xl(tmp_path, rows))
    assert all(len(r) < 100 for r in got)
    # 行长度只到有值的最大列，远处的空格不补
    mixed = read_first_sheet(xl(tmp_path, [{2: "c", 16383: Blank()}, {0: "a", 16383: Blank(styled=False)}]))
    assert mixed[0] == [None, None, "c"]
    assert mixed[1] == ["a"]


# risk: high
@pytest.mark.parametrize("where", ["sheet", "shared", "workbook"])
def test_doctype_in_any_xml_member_is_refused(tmp_path, where):
    path = xl(tmp_path, [["a", 1]], doctype_in=(where,))
    with pytest.raises(XlsxError) as ei:
        read_first_sheet(path)
    assert "DOCTYPE" in str(ei.value)


# risk: high
def test_missing_file_still_raises_filenotfounderror(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_first_sheet(str(tmp_path / "does-not-exist.xlsx"))


def _corruption_base_rows():
    return [["Name%d" % i, i, i * 1.5, Err("#N/A") if i % 7 == 0 else None, Formula(i, "A1+1")]
            for i in range(40)]


# risk: high
@pytest.mark.parametrize("stored", [False, True], ids=["deflated", "stored-xml-plaintext"])
def test_randomly_corrupted_zip_only_ever_raises_xlsxerror(tmp_path, stored):
    base = pathlib.Path(build_xlsx(tmp_path / "base.xlsx", _corruption_base_rows(), stored=stored)).read_bytes()
    rng = random.Random(20261108)
    target = tmp_path / "corrupt.xlsx"
    leaks = []
    for i in range(200):
        data = bytearray(base)
        for _ in range(rng.randint(1, 4)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        target.write_bytes(bytes(data))
        try:
            read_first_sheet(str(target))  # 正常读出也算过（翻到了无关字节）
        except XlsxError:
            pass
        except Exception as e:  # noqa: BLE001  任何别的异常类型逃出都是缺陷
            leaks.append("run %d: %s: %s" % (i, type(e).__name__, str(e)[:60]))
    assert not leaks, "%d leaked, first: %s" % (len(leaks), leaks[:5])


# risk: medium
def test_truncated_zip_raises_xlsxerror_at_every_cut(tmp_path):
    base = pathlib.Path(build_xlsx(tmp_path / "base.xlsx", _corruption_base_rows())).read_bytes()
    target = tmp_path / "cut.xlsx"
    for cut in range(0, len(base) - 1, max(1, len(base) // 60)):
        target.write_bytes(base[:cut])
        with pytest.raises(XlsxError):
            read_first_sheet(str(target))


# risk: high
@pytest.mark.parametrize("t,v", [("s", "-1"), ("s", "9999")], ids=["negative-index", "out-of-range-index"])
def test_shared_string_index_negative_or_out_of_range_raises_xlsxerror(tmp_path, t, v):
    with pytest.raises(XlsxError):
        read_first_sheet(xl(tmp_path, [["ok", RawCell(t, v)]]))  # 共享串表里只有 1 条，-1 不得读成最后一条


# risk: medium
@pytest.mark.parametrize("rows", [
    [["ok", RawCell("s", "abc")]],
    [["ok", RawCell(None, "12abc")]],
    [[RawCell("s", "0")]],  # 工作簿没有 sharedStrings.xml 却引用共享串
], ids=["non-integer-index", "garbage-number", "no-shared-strings-part"])
def test_garbage_cell_values_raise_xlsxerror_not_valueerror(tmp_path, rows):
    with pytest.raises(XlsxError):
        read_first_sheet(xl(tmp_path, rows))


# risk: high
def test_t_d_cell_returns_its_iso_text_instead_of_raising(tmp_path):
    got = read_first_sheet(xl(tmp_path, [["a", IsoDate("2026-11-25T00:00:00"), 3]]))[0]
    assert got == ["a", "2026-11-25T00:00:00", 3]
    assert type(got[1]) is str
