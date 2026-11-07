# risk: high
"""Task 5.3：`lutetia import poi FILE [--dry-run]`（FLOW-5：小雷一条命令导入台账、看汇总数字就知道对不对）。
断言依据：派单书 brief-5.3 的接口约定、Spec v1.9「POI 台账导入」（读出 0 个工单拒绝导入）；
不看 cli.py 的实现。CLI 用例走子进程 `python -m lutetia.cli`，cwd 设成临时目录（不读仓库里的 .env）。
连库用例只用本机合成库（DATABASE_URL 显式给，连不上 skip）；只 truncate poi、poi_cable_segment；工单号只用 6000xx 段。
"""
import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import asyncpg
import pytest

from xlsx_builder import RawNum, ledger_row, without_header, write_ledger

ROOT = Path(__file__).resolve().parent.parent
DB_URL = "postgresql://lutetia:lutetia@127.0.0.1:15433/lutetia"  # 开发用常量：容器 lutetia-pg，合成库
DEAD_URL = "postgresql://x:x@127.0.0.1:1/x"
OCC_OK = "OCC S48 - S49 2026/11/25 - 12/02"
RESULT_RE = re.compile(r"^result: (\d+) new, (\d+) updated, (\d+) unchanged, (\d+) raw refreshed, (\d+) gone from ledger$")
CLEANED_RE = re.compile(r"^cleaned: uci_normalised=\d+ trimmed_cells=\d+ na_to_empty=\d+ "
                        r"segment_no_cable_type=\d+ not_a_number=\d+; occ_unparsed=\d+$")
SYNTH_NO = re.compile(r"^[A-Z]{3}6000\d\d$")


# --------------------------------------------------------------------------- 工具
def run_cli(args, db_url, cwd):
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-m", "lutetia.cli"] + [str(a) for a in args], env=env, cwd=str(cwd),
                          capture_output=True, text=True, timeout=120)


def _db(coro):
    async def go():
        conn = await asyncpg.connect(DB_URL, timeout=5)
        try:
            return await coro(conn)
        finally:
            await conn.close()
    return asyncio.run(go())


@pytest.fixture
def pg():
    """本机合成库：建表（003 SQL 幂等）、确认表里只有 6000xx 合成工单、清空两张表；用完再清。"""
    if urlparse(DB_URL).hostname not in ("127.0.0.1", "localhost"):
        pytest.skip("non-local db")
    sql = (ROOT / "lutetia" / "sql" / "003_poi.sql").read_text(encoding="utf-8")

    async def prep(c):
        await c.execute(sql)
        bad = [r["poi_no"] for r in await c.fetch("SELECT poi_no FROM poi") if not SYNTH_NO.match(r["poi_no"])]
        if bad:
            return bad
        await c.execute("TRUNCATE poi_cable_segment, poi")
        return []
    try:
        bad = _db(prep)
    except Exception as e:  # noqa: BLE001
        pytest.skip("database unreachable: %s" % e)
    if bad:
        pytest.skip("poi table holds non-synthetic rows; refusing to truncate")
    yield DB_URL

    async def clean(c):
        await c.execute("TRUNCATE poi_cable_segment, poi")
    _db(clean)


def counts_in_db():
    async def q(c):
        return (await c.fetchval("SELECT count(*) FROM poi"), await c.fetchval("SELECT count(*) FROM poi_cable_segment"))
    return _db(q)


def order(poi, cables, subcon="SUBCON-A", ville="TESTVILLE", commun="44000"):
    """一个工单：首行带工单级字段与第一段，其余段为续行。cables 为 [(型号, 重量)]；空则只有工单行。"""
    rows = []
    for i, (cable, w) in enumerate(cables):
        kw = dict(cable=cable, weight=w, ref_avg=w, length=1.0 + i, infra="Aerial", cable_category="Transport")
        if i == 0:
            kw.update(poi=poi, uci="AURA", status=OCC_OK, subcon=subcon, site_ville=ville, commun=commun,
                      category="Transport", received=45000, planned=45010)
        rows.append(ledger_row(**kw))
    if not cables:
        rows.append(ledger_row(poi=poi, uci="AURA", status=OCC_OK, subcon=subcon, site_ville=ville, commun=commun,
                               category="Transport", received=45000, planned=45010))
    return rows


def three_pois(weight=2.064, **kw):
    """3 个工单：A 两段、B 一段、C 无段 -> 3 POI / 3 segments / 1 POI without cable detail。"""
    return (order("RNT600001", [("88-224-4", weight), ("88-448-4", 3.5)], **kw)
            + order("BRG600002", [("22-100-2", 0.8)], **kw) + order("CCC600003", [], **kw))


def make_file(tmp_path, rows, name="ledger.xlsx", **kw):
    return write_ledger(tmp_path / name, rows, **kw)


LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d")


def lines(r):
    """标准输出里的契约行；logging 的时间戳行（lutetia.log 默认可能写到标准输出，只含计数）不算在内。"""
    return [x for x in r.stdout.splitlines() if not LOG_LINE.match(x)]


def result_counts(r):
    ls = [x for x in lines(r) if x.startswith("result:")]
    assert len(ls) == 1, "应恰有一行 result: %r" % r.stdout
    m = RESULT_RE.match(ls[0])
    assert m, "result 行格式不对: %r" % ls[0]
    return tuple(int(g) for g in m.groups())


# --------------------------------------------------------------------------- 用例 1：输出格式与首导 / 重导 / 改一段
# risk: high
def test_first_import_prints_five_lines_and_writes_rows(pg, tmp_path):
    f = make_file(tmp_path, three_pois())
    r = run_cli(["import", "poi", f], pg, tmp_path)
    assert r.returncode == 0, r.stderr
    ls = lines(r)
    assert len(ls) == 4 or len(ls) == 5, ls
    assert ls[0] == "read: 3 POI / 3 segments (1 POI without cable detail)"
    assert result_counts(r) == (3, 0, 0, 0, 0)
    assert ls[1] == "result: 3 new, 0 updated, 0 unchanged, 0 raw refreshed, 0 gone from ledger"
    assert CLEANED_RE.match(ls[2]), ls[2]
    assert ls[3] == "suspicious: none"
    assert not any(x.startswith("dry-run") for x in ls), "没带 --dry-run 不得出现 dry-run 行"
    assert counts_in_db() == (3, 3)


# risk: high
def test_reimport_same_file_is_all_unchanged_then_one_weight_change_is_one_update(pg, tmp_path):
    f = make_file(tmp_path, three_pois())
    assert run_cli(["import", "poi", f], pg, tmp_path).returncode == 0
    r2 = run_cli(["import", "poi", f], pg, tmp_path)
    assert r2.returncode == 0, r2.stderr
    assert result_counts(r2) == (0, 0, 3, 0, 0)
    f2 = make_file(tmp_path, three_pois(weight=9.125), name="changed.xlsx")  # 只改 RNT600001 第一段的重量
    r3 = run_cli(["import", "poi", f2], pg, tmp_path)
    assert r3.returncode == 0, r3.stderr
    assert result_counts(r3) == (0, 1, 2, 0, 0)
    assert counts_in_db() == (3, 3)


# --------------------------------------------------------------------------- 用例 2：--dry-run
# risk: high
def test_dry_run_prints_marker_first_counts_as_usual_and_writes_nothing(pg, tmp_path):
    f = make_file(tmp_path, three_pois())
    r = run_cli(["import", "poi", f, "--dry-run"], pg, tmp_path)
    assert r.returncode == 0, r.stderr
    ls = lines(r)
    assert ls[0] == "dry-run: nothing written"
    assert ls[1] == "read: 3 POI / 3 segments (1 POI without cable detail)"
    assert result_counts(r) == (3, 0, 0, 0, 0)
    assert counts_in_db() == (0, 0)
    assert run_cli(["import", "poi", f], pg, tmp_path).returncode == 0
    f2 = make_file(tmp_path, three_pois(weight=9.125), name="changed.xlsx")
    r2 = run_cli(["import", "poi", f2, "--dry-run"], pg, tmp_path)
    assert lines(r2)[0] == "dry-run: nothing written"
    assert result_counts(r2) == (0, 1, 2, 0, 0)
    assert counts_in_db() == (3, 3)
    r3 = run_cli(["import", "poi", f], pg, tmp_path)  # 干跑没留下痕迹：原文件仍是全 unchanged
    assert result_counts(r3) == (0, 0, 3, 0, 0)


# --------------------------------------------------------------------------- 用例 3 / 4 / 9：错误路径，不连库
# risk: high
@pytest.mark.parametrize("url", [DEAD_URL, DB_URL], ids=["dead-db", "real-db-url"])
def test_missing_poi_header_is_error_exit1_without_touching_db(tmp_path, url):
    f = make_file(tmp_path, three_pois(), headers=without_header("POI"))
    r = run_cli(["import", "poi", f], url, tmp_path)
    assert r.returncode == 1
    assert "error: missing column: POI" in r.stderr
    assert "result:" not in r.stdout
    assert "Traceback" not in r.stderr


# risk: high
@pytest.mark.parametrize("url", [DEAD_URL, DB_URL], ids=["dead-db", "real-db-url"])
def test_missing_file_is_error_exit1(tmp_path, url):
    missing = tmp_path / "nope.xlsx"
    r = run_cli(["import", "poi", missing], url, tmp_path)
    assert r.returncode == 1
    assert "error: file not found: %s" % missing in r.stderr
    assert r.stdout.strip() == ""
    assert "Traceback" not in r.stderr


# risk: high
def test_not_an_xlsx_file_is_error_exit1_without_db(tmp_path):
    f = tmp_path / "fake.xlsx"
    f.write_bytes(b"this is not a zip file")
    r = run_cli(["import", "poi", f], DEAD_URL, tmp_path)
    assert r.returncode == 1
    assert r.stderr.strip().startswith("error:") or "\nerror:" in r.stderr
    assert "Traceback" not in r.stderr
    assert "result:" not in r.stdout


# risk: high
@pytest.mark.parametrize("flags", [[], ["--dry-run"]], ids=["real", "dry-run"])
def test_header_only_ledger_is_rejected_without_db(tmp_path, flags):
    f = make_file(tmp_path, [])
    r = run_cli(["import", "poi", f] + flags, DEAD_URL, tmp_path)
    assert r.returncode == 1
    assert "error: no POI rows in ledger" in r.stderr
    assert "result:" not in r.stdout
    assert "Traceback" not in r.stderr


# risk: high
def test_header_only_ledger_does_not_mark_existing_pois_gone(pg, tmp_path):
    assert run_cli(["import", "poi", make_file(tmp_path, three_pois())], pg, tmp_path).returncode == 0
    r = run_cli(["import", "poi", make_file(tmp_path, [], name="empty.xlsx")], pg, tmp_path)
    assert r.returncode == 1
    assert "error: no POI rows in ledger" in r.stderr
    assert "result:" not in r.stdout

    async def q(c):
        return [(x["poi_no"], x["in_ledger"]) for x in await c.fetch("SELECT poi_no, in_ledger FROM poi ORDER BY poi_no")]
    assert _db(q) == [("BRG600002", True), ("CCC600003", True), ("RNT600001", True)]
    assert counts_in_db() == (3, 3)


# --------------------------------------------------------------------------- 用例 5：不泄漏行内容
# risk: high
@pytest.mark.parametrize("flags", [[], ["--dry-run"]], ids=["real", "dry-run"])
def test_output_never_echoes_row_content(pg, tmp_path, flags):
    rows = (order("RNT600001", [("CABLE-MODEL-ZZ9", 7.77)], subcon="SUBCON-ZZ9", ville="COMMUNE-ZZ9", commun="ZZ999")
            + order("BRG600002", [("22-100-2", 0.8)], subcon="SUBCON-ZZ9", ville="COMMUNE-ZZ9"))
    r = run_cli(["import", "poi", make_file(tmp_path, rows)] + flags, pg, tmp_path)
    assert r.returncode == 0, r.stderr
    for secret in ("SUBCON-ZZ9", "COMMUNE-ZZ9", "CABLE-MODEL-ZZ9", "7.77", "ZZ999"):
        assert secret not in r.stdout and secret not in r.stderr, secret


# risk: high
def test_malformed_poi_number_listed_on_suspicious_line_only(pg, tmp_path):
    rows = three_pois() + order("BAD60004", [("22-100-2", 0.8)], subcon="SUBCON-ZZ9", ville="COMMUNE-ZZ9")
    r = run_cli(["import", "poi", make_file(tmp_path, rows)], pg, tmp_path)
    assert r.returncode == 0, r.stderr
    sus = [x for x in lines(r) if x.startswith("suspicious:")]
    assert sus == ["suspicious: BAD60004"]
    assert "SUBCON-ZZ9" not in r.stdout + r.stderr and "COMMUNE-ZZ9" not in r.stdout + r.stderr


# risk: medium
def test_several_suspicious_numbers_are_comma_space_separated(pg, tmp_path):
    rows = three_pois() + order("BAD60004", [("22-100-2", 0.8)]) + order("BAD60005", [("22-100-2", 0.8)])
    r = run_cli(["import", "poi", make_file(tmp_path, rows)], pg, tmp_path)
    assert r.returncode == 0, r.stderr
    sus = [x for x in lines(r) if x.startswith("suspicious:")][0]
    assert sus in ("suspicious: BAD60004, BAD60005", "suspicious: BAD60005, BAD60004")


# --------------------------------------------------------------------------- 用例 6：解析器
# risk: medium
def test_parser_has_import_poi_with_dry_run_default_false():
    from lutetia.cli import build_parser
    a = build_parser().parse_args(["import", "poi", "x.xlsx"])
    assert a.dry_run is False
    assert "x.xlsx" in [str(v) for v in vars(a).values()]
    b = build_parser().parse_args(["import", "poi", "x.xlsx", "--dry-run"])
    assert b.dry_run is True


# --------------------------------------------------------------------------- 用例 7：部署文本
def _collector_block(text):
    m = re.search(r"^  collector:\n(.*?)(?=^  \S|^\S|\Z)", text, re.M | re.S)
    assert m, "docker-compose.yml 里找不到 collector 服务"
    return m.group(1)


# risk: high
def test_compose_mounts_ledger_read_only_and_keeps_state_volume():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    block = _collector_block(text)
    assert re.search(r"^\s*-\s*\./data/poi:/ledger:ro\s*$", block, re.M), "collector 缺 ./data/poi:/ledger:ro"
    assert re.search(r"^\s*-\s*lutetia-state:/data\s*$", block, re.M), "原有 lutetia-state:/data 必须还在 collector 里"
    assert re.search(r"^  lutetia-state:", text, re.M) or re.search(r"^\s+lutetia-state:\s*$", text, re.M)


# risk: high
def test_dockerfile_copies_only_package_files_so_data_dir_stays_out_of_image():
    copies = [ln.split()[1:] for ln in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
              if ln.strip().upper().startswith("COPY")]
    sources = {s for args in copies for s in args[:-1]}
    assert sources == {"pyproject.toml", "README.md", "lutetia"}, sources


# risk: low
def test_readme_documents_import_command():
    assert "lutetia import poi" in (ROOT / "README.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- Task 5.3 审查回补：M-1 / L-1 / L-2 / L-4
SECRET_SUBCON = "SUBCON-ZZ9"
DRY_LINE_RES = [
    re.compile(r"^dry-run: nothing written$"),
    re.compile(r"^read: \d+ POI / \d+ segments \(\d+ POI without cable detail\)$"),
    RESULT_RE,
    CLEANED_RE,
    re.compile(r"^suspicious: .+$"),
]


def _db_error_line(stderr):
    hits = [x for x in stderr.splitlines() if x.startswith("error: database: ")]
    assert len(hits) >= 1, "stderr 应有以 'error: database: ' 开头的一行: %r" % stderr
    return hits[0]


# risk: medium
def test_unreachable_database_is_one_error_line_not_traceback(tmp_path):
    rows = order("RNT600001", [("22-100-2", 0.8)], subcon=SECRET_SUBCON)
    r = run_cli(["import", "poi", make_file(tmp_path, rows)], DEAD_URL, tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "nothing written" in _db_error_line(r.stderr)
    assert "Traceback" not in r.stderr
    assert "result:" not in r.stdout
    assert SECRET_SUBCON not in r.stdout + r.stderr


# risk: medium
def test_db_write_failure_is_one_error_line_and_leaves_poi_empty(pg, tmp_path):
    rows = order("RNT600001", [("22-100-2", 0.8)], subcon=SECRET_SUBCON)
    rows[0][9] = RawNum("NaN")  # Executed Weight（第一组，未映射列，只进原文）
    r = run_cli(["import", "poi", make_file(tmp_path, rows)], pg, tmp_path)
    assert r.returncode == 1, (r.stdout, r.stderr)
    _db_error_line(r.stderr)
    assert "Traceback" not in r.stderr
    assert "result:" not in r.stdout
    assert SECRET_SUBCON not in r.stdout + r.stderr
    assert counts_in_db()[0] == 0


def run_cli_no_db_env(args, cwd):
    env = dict(os.environ)
    env.pop("DATABASE_URL", None)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-m", "lutetia.cli"] + [str(a) for a in args], env=env, cwd=str(cwd),
                          capture_output=True, text=True, timeout=120)


# risk: medium
def test_without_database_url_header_only_ledger_reports_ledger_problem_first(tmp_path):
    r = run_cli_no_db_env(["import", "poi", make_file(tmp_path, [])], tmp_path)
    assert r.returncode == 1
    assert "error: no POI rows in ledger" in r.stderr
    assert "Traceback" not in r.stderr


# risk: medium
def test_without_database_url_valid_ledger_asks_for_database_url(tmp_path):
    r = run_cli_no_db_env(["import", "poi", make_file(tmp_path, order("RNT600001", [("22-100-2", 0.8)]))], tmp_path)
    assert r.returncode == 1
    assert any(x.startswith("error: ") and "DATABASE_URL" in x for x in r.stderr.splitlines()), r.stderr
    assert "Traceback" not in r.stderr
    assert "result:" not in r.stdout


# risk: medium
def test_cleaning_warnings_go_to_stderr_not_stdout(pg, tmp_path):
    rows = order("RNT600001", [("22-100-2", "2,95")])
    rows[0][20] = "hello"  # Recieve date
    r = run_cli(["import", "poi", make_file(tmp_path, rows), "--dry-run"], pg, tmp_path)
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    assert len(out) == 5, out
    for ln, rx in zip(out, DRY_LINE_RES):
        assert rx.match(ln), ln
    assert any("not a number" in x for x in r.stderr.splitlines()), r.stderr
    for raw in ("2,95", "hello"):
        assert raw not in r.stdout and raw not in r.stderr, raw


# risk: low
def test_dockerignore_excludes_data_dir():
    text = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert any(ln.strip() in ("data/", "data") for ln in text.splitlines()), ".dockerignore 缺 data/ 行"
