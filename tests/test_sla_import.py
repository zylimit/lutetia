# risk: medium
"""Task 10.3：SLA 模板导入（`lutetia import sla`）与 GET /api/v1/sla-templates。
断言依据：DEV-PLAN Task 10.3（表结构、整模板替换、日志不打单元格内容）、Spec「SLA 流程参考」（只作参考，不算超时）。
只用 tests/xlsx_builder.py 造的合成模板（文本全是 zz-* 占位），不读 data/ 下任何真表。
连库用例只用 DATABASE_URL 指向的本机合成库；只清理三个模板名与 zz-test-v1-* 的行。
"""
import asyncio
import os
from decimal import Decimal
import subprocess
import sys
from pathlib import Path

import asyncpg
import pytest
from aiohttp import DummyCookieJar
from aiohttp.test_utils import TestClient, TestServer

from test_api_v1_resources import AUTH, DB_URL, PFX, _entry, get_json, login, make_app
from test_api_v1_resources import db as sla_db  # noqa: F401  (fixture under another name)
from xlsx_builder import build_xlsx

from lutetia.sla_import import SlaError, parse_duration, parse_template, template_name

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("Transportation", "Distribution", "MASSIVE")
HEAD = ["Number*", "Name*", "Plan Start Date", "SLA典型时长", "Responsible party*"]
SENTINEL = "zz-secret-node-text"


def tpl_rows(n=3, owners=("客户", "华为", "合作方"), head=HEAD, sla=True, tag=SENTINEL):
    rows = [list(head)]
    for i in range(1, n + 1):
        rows.append([i, "%s-%d" % (tag, i), "T0", ("%d工作日" % i) if sla and i != 2 else None, owners[(i - 1) % len(owners)]])
    return rows


def make(tmp_path, name, rows):
    p = tmp_path / ("DEPOSE-%s.xlsx" % name)
    build_xlsx(p, rows)
    return p


def run_cli(args, db_url=None):
    env = dict(os.environ)
    env["DATABASE_URL"] = db_url or DB_URL
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run([sys.executable, "-m", "lutetia.cli", "import", "sla"] + [str(a) for a in args], env=env,
                          cwd=str(ROOT.parent), capture_output=True, text=True, timeout=120)


def q(sql, *args):
    async def go():
        conn = await asyncpg.connect(DB_URL, timeout=5)
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()
    return asyncio.run(go())


def steps_in_db(template):
    return [tuple(r) for r in q("SELECT seq, step, owner, sla_text FROM sla_template_step WHERE template = $1 ORDER BY seq", template)]


@pytest.fixture
async def sla(sla_db):  # noqa: F811
    db = sla_db
    async def clean():
        async with db.pool.acquire() as conn:
            await conn.execute("DELETE FROM sla_template_step WHERE template = ANY($1::text[]) OR template LIKE $2", list(NAMES), PFX + "%")
    await db.migrate(ROOT / "lutetia" / "sql")
    await clean()
    yield db
    await clean()


# ---- 解析（纯函数，不连库）----------------------------------------------------------------------------------------------

def test_parse_maps_owners_keeps_order_and_sla_text_as_written(tmp_path):
    t = parse_template(make(tmp_path, "Transportation", tpl_rows(4)))
    assert t.template == "Transportation"
    assert [s.seq for s in t.steps] == [1, 2, 3, 4]
    assert [s.owner for s in t.steps] == ["customer", "huawei", "partner", "customer"]
    assert [s.sla_text for s in t.steps] == ["1工作日", None, "3工作日", "4工作日"]  # 表里没写时长 → None，不是空串
    assert t.steps[0].step == SENTINEL + "-1"


def test_parse_skips_trailing_blank_rows_and_accepts_extra_columns_in_any_order(tmp_path):
    head = ["Responsible party*", "junk", "SLA典型时长", "Name*", "Number*"]
    rows = [head, ["客户", "x", "1工作日", "a", 1], ["华为", "x", None, "b", 2], [None, None, None, None, None]]
    t = parse_template(make(tmp_path, "MASSIVE", rows))
    assert [(s.seq, s.step, s.owner) for s in t.steps] == [(1, "a", "customer"), (2, "b", "huawei")]


@pytest.mark.parametrize("text, expected", [
    ("1工作日", (1, None, "workday")),
    ("15 个工作日", (15, None, "workday")),
    ("２工作日", (2, None, "workday")),  # 全角数字
    ("3天", (3, None, "day")),
    ("3日", (3, None, "day")),
    ("5 自然日", (5, None, "day")),
    ("1-2天", (2, 1, "day")),  # 范围：value 存上限，value_min 存下限
    ("1～2天", (2, 1, "day")),
    ("2至3周", (3, 2, "week")),
    ("≤3天", (3, None, "day")),
    ("3天内", (3, None, "day")),
    ("不超过 5 工作日", (5, None, "workday")),
    ("48小时", (48, None, "hour")),
    ("0.5小时", (Decimal("0.5"), None, "hour")),
    ("30分钟", (30, None, "minute")),
    ("2周", (2, None, "week")),
    ("两周", (2, None, "week")),
    ("1个月", (1, None, "month")),
    ("2 days", (2, None, "day")),
    ("4 h", (4, None, "hour")),
    ("接入层：1吨/天", (1, None, "tonne_per_day")),  # 拆除节点的产能写法
    ("主干层:2吨/天", (2, None, "tonne_per_day")),
])
def test_parse_duration_known_forms(text, expected):
    d = parse_duration(text)
    assert d is not None, text
    assert (d.value, d.value_min, d.unit) == (Decimal(expected[0]), None if expected[1] is None else Decimal(expected[1]), expected[2])
    assert d.scope == ("access" if text.startswith("接入层") else "backbone" if text.startswith("主干层") else None)


@pytest.mark.parametrize("text, scope", [
    ("接入层：1吨/天", "access"),
    ("汇聚层：1.5吨/天", "aggregation"),
    ("主干层：2吨/天", "backbone"),
    ("骨干层:2吨/天", "backbone"),
    ("zz某层：3工作日", "other"),  # 不认识的前缀：值照解析，层级记 other，前端注「scope in source table」
    ("3工作日", None),
])
def test_parse_duration_scope_prefix(text, scope):
    d = parse_duration(text)
    assert d is not None and d.scope == scope


@pytest.mark.parametrize("text", [None, "", "按照80用户每工作日排程", "3-1天", "看情况", "2", "天", "1-2",
                                  "接入层：主干层：1吨/天",  # 两个冒号：不猜（审查 L-1）
                                  "二月", "三月", "2月", "12月"])  # 月份名不是时长（审查 L-2）；时长要写「个月」
def test_parse_duration_unknown_forms_give_none(text):
    assert parse_duration(text) is None  # 解析不了：两列 NULL，原文照存，前端显示「—」


def test_parse_template_attaches_durations_and_counts_unparsed(tmp_path):
    rows = tpl_rows(3)
    rows[3][3] = "zz-free-text"
    t = parse_template(make(tmp_path, "Distribution", rows))
    assert [(s.duration.value, s.duration.unit) if s.duration else None for s in t.steps] == [(1, "workday"), None, None]
    assert t.unparsed == 1  # 第 2 步没写时长，不算解析不了


@pytest.mark.parametrize("name", ["Other", "Transportation2"])
def test_unknown_template_file_name_is_refused(tmp_path, name):
    with pytest.raises(SlaError):
        template_name(tmp_path / ("DEPOSE-%s.xlsx" % name))


def test_missing_header_names_the_column_only(tmp_path):
    rows = tpl_rows(2, head=["Number*", "Name*", "SLA典型时长", "Responsible party (typo)"])
    with pytest.raises(SlaError) as e:
        parse_template(make(tmp_path, "Distribution", rows))
    assert "Responsible party*" in str(e.value) and SENTINEL not in str(e.value)


def test_unknown_owner_is_an_error_without_cell_text(tmp_path):
    rows = tpl_rows(3)
    rows[2][4] = "zz-unknown-party"
    with pytest.raises(SlaError) as e:
        parse_template(make(tmp_path, "Distribution", rows))
    assert "row 3" in str(e.value) and "zz-unknown-party" not in str(e.value) and SENTINEL not in str(e.value)


@pytest.mark.parametrize("bad", ["x", 1.5, 0, None])
def test_bad_step_number_is_refused(tmp_path, bad):
    rows = tpl_rows(2)
    rows[2][0] = bad
    with pytest.raises(SlaError):
        parse_template(make(tmp_path, "MASSIVE", rows))


def test_duplicate_step_number_and_empty_template_are_refused(tmp_path):
    rows = tpl_rows(2)
    rows[2][0] = 1
    with pytest.raises(SlaError):
        parse_template(make(tmp_path, "MASSIVE", rows))
    with pytest.raises(SlaError):
        parse_template(make(tmp_path, "Transportation", [list(HEAD)]))


# ---- CLI + 库 ---------------------------------------------------------------------------------------------------------

def test_import_writes_all_files_and_prints_name_and_step_count_only(tmp_path, sla):
    dist = tpl_rows(2)
    dist[1][3] = "主干层：2吨/天"
    files = [make(tmp_path, "Transportation", tpl_rows(3)), make(tmp_path, "Distribution", dist),
             make(tmp_path, "MASSIVE", tpl_rows(4))]
    r = run_cli(files)
    assert r.returncode == 0, r.stderr
    assert [tuple(x) for x in q("SELECT sla_value, sla_unit, sla_scope FROM sla_template_step WHERE template = 'Distribution' AND seq = 1")] \
        == [(Decimal(2), "tonne_per_day", "backbone")]
    assert "主干层" not in r.stdout + r.stderr  # 计数里只有层级代号，不带原文
    assert r.stdout.splitlines() == ["Transportation: 3 steps", "Distribution: 2 steps", "MASSIVE: 4 steps"]
    assert SENTINEL not in r.stdout + r.stderr
    assert steps_in_db("Transportation") == [(1, SENTINEL + "-1", "customer", "1工作日"), (2, SENTINEL + "-2", "huawei", None),
                                             (3, SENTINEL + "-3", "partner", "3工作日")]
    assert len(steps_in_db("MASSIVE")) == 4
    parsed = [tuple(r) for r in q("SELECT sla_value, sla_value_min, sla_unit FROM sla_template_step WHERE template = 'Transportation' ORDER BY seq")]
    assert parsed == [(Decimal(1), None, "workday"), (None, None, None), (Decimal(3), None, "workday")]
    assert [r[0] for r in q("SELECT sla_scope FROM sla_template_step WHERE template = 'Transportation' ORDER BY seq")] == [None, None, None]


def test_import_twice_leaves_the_same_rows_and_replaces_a_whole_template(tmp_path, sla):
    p = make(tmp_path, "Transportation", tpl_rows(3))
    other = make(tmp_path, "Distribution", tpl_rows(2))
    assert run_cli([p, other]).returncode == 0
    first = steps_in_db("Transportation")
    assert run_cli([p]).returncode == 0
    assert steps_in_db("Transportation") == first  # 幂等
    assert len(steps_in_db("Distribution")) == 2  # 本次没出现的模板不动
    shorter = make(tmp_path, "Transportation", tpl_rows(2, tag="zz-new"))
    assert run_cli([shorter]).returncode == 0
    got = steps_in_db("Transportation")
    assert [g[0] for g in got] == [1, 2] and got[0][1] == "zz-new-1"  # 整模板替换，旧的第 3 步不残留


def test_dry_run_writes_nothing_but_reports_counts(tmp_path, sla):
    r = run_cli([make(tmp_path, "Transportation", tpl_rows(3)), "--dry-run"])
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["dry-run: nothing written", "Transportation: 3 steps"]
    assert steps_in_db("Transportation") == []


def test_missing_header_or_unknown_owner_fails_and_the_database_is_unchanged(tmp_path, sla):
    good = make(tmp_path, "Transportation", tpl_rows(3))
    assert run_cli([good]).returncode == 0
    before = steps_in_db("Transportation")
    bad_head = make(tmp_path, "Distribution", tpl_rows(2, head=["Number*", "Name*", "SLA典型时长"]))
    bad_owner_rows = tpl_rows(2)
    bad_owner_rows[1][4] = "zz-unknown-party"
    bad_owner = make(tmp_path, "MASSIVE", bad_owner_rows)
    replaced = make(tmp_path, "Transportation", tpl_rows(1, tag="zz-new"))
    for bad in (bad_head, bad_owner):
        r = run_cli([replaced, bad])  # 好文件排在前面：只要有一份不对，整批都不写
        assert r.returncode == 1 and r.stderr.startswith("error:"), r.stderr
        assert SENTINEL not in r.stdout + r.stderr and "zz-unknown-party" not in r.stdout + r.stderr
        assert steps_in_db("Transportation") == before
        assert steps_in_db("Distribution") == [] and steps_in_db("MASSIVE") == []


def test_unreachable_database_reports_the_class_not_the_cells(tmp_path):
    r = run_cli([make(tmp_path, "Transportation", tpl_rows(2))], db_url="postgresql://x:x@127.0.0.1:1/x")
    assert r.returncode == 1 and "nothing written" in r.stderr
    assert SENTINEL not in r.stdout + r.stderr


def test_missing_file_is_an_error(tmp_path):
    r = run_cli([tmp_path / "DEPOSE-Transportation.xlsx"])
    assert r.returncode == 1 and "file not found" in r.stderr


# ---- GET /api/v1/sla-templates ----------------------------------------------------------------------------------------

async def seed(database, name, n):
    async with database.pool.acquire() as conn:
        for i in range(1, n + 1):
            await conn.execute("INSERT INTO sla_template_step (template, seq, step, owner, sla_text, sla_value, sla_value_min, sla_unit, "
                               "sla_scope) VALUES ($1, $2, $3, 'huawei', $4, $5, $6, $7, $8)", name, i, "step-%d" % i,
                               None if i == 2 else "%d d" % i, None if i == 2 else Decimal(i), Decimal(1) if i == 3 else None,
                               None if i == 2 else "day", "access" if i == 1 else None)


async def test_api_lists_templates_with_ordered_steps_for_orange_session_and_pages(sla, tmp_path):
    await seed(sla, PFX + "sla-b", 2)
    await seed(sla, PFX + "sla-a", 3)
    app, cfg = make_app(sla, tmp_path, [])
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        orange = await login(c, cfg, "orange")
        body = await get_json(c, "/api/v1/sla-templates?limit=1", orange)
        assert body["source"] == "excel-snapshot" and body["as_of"].endswith("Z") and body["next"]
        assert [i["template"] for i in body["items"]] == [PFX + "sla-a"]
        assert body["items"][0]["steps"] == [
            {"seq": 1, "step": "step-1", "owner": "huawei", "sla_text": "1 d", "sla_value": 1, "sla_value_min": None, "sla_unit": "day",
             "sla_scope": "access"},
            {"seq": 2, "step": "step-2", "owner": "huawei", "sla_text": None, "sla_value": None, "sla_value_min": None, "sla_unit": None,
             "sla_scope": None},
            {"seq": 3, "step": "step-3", "owner": "huawei", "sla_text": "3 d", "sla_value": 3, "sla_value_min": 1, "sla_unit": "day",
             "sla_scope": None}]
        page2 = await get_json(c, "/api/v1/sla-templates?limit=1&cursor=" + body["next"], orange)
        assert [i["template"] for i in page2["items"]] == [PFX + "sla-b"] and page2["next"] is None
        assert (await c.get("/api/v1/sla-templates?limit=0", headers=orange)).status == 400


async def test_api_scopes_401_403(sla, tmp_path):
    import secrets
    keys = {n: secrets.token_hex(12) for n in ("iot", "poi")}
    app, cfg = make_app(sla, tmp_path, [_entry("iot", keys["iot"], ["iot:read"]), _entry("poi", keys["poi"], ["poi:read"])])
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        assert (await c.get("/api/v1/sla-templates")).status == 401
        r = await c.get("/api/v1/sla-templates", headers={"Authorization": "Bearer " + keys["iot"]})
        assert r.status == 403 and await r.json() == {"error": "forbidden"}
        assert (await c.get("/api/v1/sla-templates", headers={"Authorization": "Bearer " + keys["poi"]})).status == 200


async def test_api_empty_table_gives_no_items_and_null_as_of(sla, tmp_path):
    async with sla.pool.acquire() as conn:
        if await conn.fetchval("SELECT count(*) FROM sla_template_step"):
            pytest.skip("sla_template_step holds rows of its own")
    app, cfg = make_app(sla, tmp_path, [])
    async with TestClient(TestServer(app), cookie_jar=DummyCookieJar()) as c:
        body = await get_json(c, "/api/v1/sla-templates", AUTH)
        assert body == {"items": [], "as_of": None, "next": None, "source": "excel-snapshot"}
