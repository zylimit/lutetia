# risk: medium
"""Phase 6 缺口补测（第 2 步测试完整性）：既有三份测试没碰到、但脚本 / Spec 已声明的错误、空、边界分支。

依据 DEV-PLAN Task 6.1 / 6.2 / 6.3 与脚本头部注释：阈值「超过 26 小时」不含 26 整；失败要留行；空备份视为失败；
演练的用法错误退出码 2、空文件与缺表一律失败且不起容器。合成库 :15433 + 容器 lutetia-pg 不在则 skip。
"""
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from test_backup_script import Env as BackupEnv, REAL_DOCKER, CONTAINER, _psql, _write_exe, dumps
from test_restore_drill import Env as DrillEnv, BEFORE, NAME, AFTER, TABLES
from lutetia.web import anomalies

NOW = datetime(2026, 11, 9, 3, 0, 0, tzinfo=timezone.utc)
DB_URL = os.environ.get("DATABASE_URL", "")


@pytest.fixture(scope="module")
def _guard():
    if not DB_URL or ":15433/" not in DB_URL:
        pytest.skip("DATABASE_URL not set to synthetic db (:15433)")
    if not REAL_DOCKER or subprocess.run([REAL_DOCKER, "exec", CONTAINER, "true"], capture_output=True).returncode != 0:
        pytest.skip("docker / lutetia-pg not available")
    if _psql("select to_regclass('backup_run')") != "backup_run":
        pytest.skip("backup_run table missing")


@pytest.fixture
def benv(tmp_path, _guard):
    e = BackupEnv(tmp_path)
    _write_exe(e.shims / "docker",
               '#!/bin/bash\nshift 4\nif [[ " $* " == *" pg_dump "* ]]; then\n'
               '  case "$DUMP_MODE" in empty) exit 0 ;; fail) echo boom >&2; exit 3 ;; esac\nfi\n'
               'exec "%s" exec -i %s "$@"\n' % (REAL_DOCKER, CONTAINER))
    yield e
    _psql("delete from backup_run where id > %d" % e.baseline)


@pytest.fixture
def denv(tmp_path, _guard):
    e = DrillEnv(tmp_path)
    yield e
    _psql("delete from backup_run where id > %d" % e.baseline)


def summ(last_ok_h, latest_ok=True, error=None):
    last = NOW - timedelta(hours=last_ok_h) if last_ok_h is not None else None
    return {"last_ok_at": last, "last_ok_bytes": 1, "latest_ok": latest_ok, "latest_at": last, "latest_error": error}


def items(s):
    return anomalies.compute(NOW, [], [], [], None, [], 1400, 3.4, backup=s)


# --- 6.2 看板规则的边界 ---
def test_exactly_26h_is_not_overdue_but_just_over_is():
    assert items(summ(26)) == []
    assert len(items(summ(26.01))) == 1


def test_stale_success_and_failed_latest_yield_two_red_items():
    got = items(summ(30, latest_ok=False, error="x"))
    assert [i["kind"] for i in got] == ["backup", "backup"] and all(i["level"] == "red" for i in got)


def test_never_succeeded_and_latest_failed_yield_two_items_with_no_error_text_fallback():
    got = items({"last_ok_at": None, "last_ok_bytes": None, "latest_ok": False, "latest_at": NOW, "latest_error": None})
    assert [i["detail"] for i in got] == ["no successful backup yet", "latest backup failed: no error message"]


# --- 6.1 备份脚本失败分支 ---
def test_pg_dump_nonzero_records_failed_row_and_leaves_no_dump_or_partial(benv):
    r = benv.run(["--local-only"], extra={"DUMP_MODE": "fail"})
    assert r.returncode != 0
    (row,) = benv.rows()
    assert row["ok"] is False and "stage=dump" in row["error"] and row["object_key"] is None
    assert list(benv.backup_dir.glob("lutetia-*")) == []


def test_empty_dump_is_a_failed_run_not_ok(benv):
    r = benv.run(["--local-only"], extra={"DUMP_MODE": "empty"})
    assert r.returncode != 0
    (row,) = benv.rows()
    assert row["ok"] is False and "备份文件为空" in row["error"]
    assert list(benv.backup_dir.glob("lutetia-*.dump")) == []  # 不留 0 字节 .dump
    assert list(benv.backup_dir.glob("lutetia-*.partial")) == []


# --- 6.3 演练脚本用法与前置失败 ---
def test_drill_unknown_arg_exits_2(denv):
    assert denv.run(["--bogus"]).returncode == 2
    assert denv.docker_calls() == []


def test_drill_file_and_from_cos_together_exits_2(denv):
    r = denv.run(["--file", str(denv.dump), "--from-cos"])
    assert r.returncode == 2 and "二选一" in r.stderr
    assert denv.docker_calls() == []


def test_drill_empty_dump_file_fails_without_starting_container(denv):
    denv.add_run()
    denv.dump.write_bytes(b"")
    r = denv.run(["--file", str(denv.dump)])
    assert r.returncode == 1 and "为空" in r.stderr
    assert not any(c.startswith("run ") for c in denv.docker_calls())


def test_drill_bounds_missing_a_table_fails_that_table_never_passes(denv):
    partial = {k: v for k, v in BEFORE.items() if k != "poi"}
    _psql("insert into backup_run (started_at, finished_at, ok, kind, object_key, sha256, row_counts, row_counts_after) "
          "values (now(), now(), true, 'daily', 'daily/%s', '%s', '%s'::jsonb, '%s'::jsonb)"
          % (NAME, hashlib.sha256(denv.dump.read_bytes()).hexdigest(), json.dumps(partial), json.dumps(AFTER)))
    r = denv.run(["--file", str(denv.dump)])
    # 缺一端区间不能当通过：该表明确报缺、整体退出 1
    assert r.returncode == 1
    (bad,) = [l for l in r.stdout.splitlines() if l.endswith("  FAIL")]
    assert bad.startswith("poi ") and "没有该表的行数区间" in bad
    assert len([l for l in r.stdout.splitlines() if l.endswith("  OK")]) == 6
