# risk: high
"""deploy/restore-drill.sh 行为回归（Task 6.3）：PATH 垫片替换 docker / coscli，真跑脚本，真读合成库 backup_run。

断言依据 DEV-PLAN Task 6.3 与 Business Context，不照抄脚本实现：
恢复值必须满足 前 <= 恢复 <= 后（含两端）；找不到对应 backup_run 行即失败；
临时容器与网络无论成败都要删；--check-delete-denied 以「rm 之后对象还在不在」为准（读配置 ls 复查），不信 rm 退出码，不确定不 PASS。
垫片：`docker compose exec -T db ...` 转发到合成库容器 lutetia-pg；
临时容器相关（network / run / exec / rm）由垫片模拟，恢复后的行数由 FAKE_COUNTS 文件给定。
只在 DATABASE_URL 指向合成库（:15433）且容器 lutetia-pg 在跑时才执行，否则 skip。
"""
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from lutetia.config import load_dotenv

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
CONTAINER = "lutetia-pg"
REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "deploy" / "restore-drill.sh"
REAL_DOCKER = shutil.which("docker") or ""
TABLES = ["device", "gps_position", "sensor_telemetry", "sensor_attribute", "api_call", "poi", "poi_cable_segment"]
BEFORE = {"device": 10, "gps_position": 1000, "sensor_telemetry": 160000, "sensor_attribute": 50,
          "api_call": 300, "poi": 20, "poi_cable_segment": 5}
AFTER = dict(BEFORE, sensor_telemetry=160008, gps_position=1004)
STAMP = "20990101T000000Z"
NAME = "lutetia-%s.dump" % STAMP
SECRET_PW_HINT = "POSTGRES_PASSWORD"


def _psql(sql):
    r = subprocess.run([REAL_DOCKER, "exec", "-i", CONTAINER, "psql", "-U", "lutetia", "-d", "lutetia",
                        "-tAq", "-c", sql], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture(scope="module", autouse=True)
def _guard():
    if not DB_URL or ":15433/" not in DB_URL:
        pytest.skip("DATABASE_URL not set to synthetic db (:15433)")
    if not REAL_DOCKER:
        pytest.skip("docker not available")
    r = subprocess.run([REAL_DOCKER, "exec", CONTAINER, "true"], capture_output=True)
    if r.returncode != 0:
        pytest.skip("container lutetia-pg not running")
    if _psql("select to_regclass('backup_run')") != "backup_run":
        pytest.skip("backup_run table missing (migrate first)")


def _write_exe(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


DOCKER_SHIM = r'''#!/bin/bash
echo "$*" >> "$DOCKER_LOG"
if [ "$1 $2 $3 $4" = "compose exec -T db" ]; then
  shift 4
  exec "%(real)s" exec -i %(ctr)s "$@"
fi
case "$1" in
  network) [ "$2" = "create" ] && exit "${FAKE_NETWORK_RC:-0}"; exit 0 ;;
  run) exit "${FAKE_RUN_RC:-0}" ;;
  rm) exit 0 ;;
  exec)
    if [[ " $* " == *" pg_isready "* ]]; then exit 0; fi
    if [[ " $* " == *" pg_restore "* ]]; then cat > /dev/null; exit "${FAKE_RESTORE_RC:-0}"; fi
    if [[ " $* " == *" psql "* ]]; then cat "$FAKE_COUNTS_FILE"; exit 0; fi
    ;;
esac
echo "unexpected docker args: $*" >&2; exit 97
''' % {"real": REAL_DOCKER, "ctr": CONTAINER}

COSCLI_SHIM = r'''#!/bin/bash
echo "$*" >> "$COSCLI_LOG"
args=("$@")
[ "${args[0]}" = "-c" ] && { [ -f "${args[1]}" ] || exit 9; args=("${args[@]:2}"); }
case "${args[0]}" in
  ls)
    case "${args[1]}" in
      */daily/) printf '%s\n' "daily/lutetia-20990101T000000Z.dump  1234" "daily/lutetia-20980101T000000Z.dump  999"; exit 0 ;;
      *.dump)
        if [ -f "$COSCLI_LOG.rmdone" ]; then
          [ "${FAKE_LS_POST_ERR:-0}" = 1 ] && exit 1
          [ "${FAKE_RM_DELETES:-0}" = 1 ] && exit 0
        else
          [ "${FAKE_LS_PRE_ERR:-0}" = 1 ] && exit 1
          [ "${FAKE_OBJECT_ABSENT:-0}" = 1 ] && exit 0
        fi
        echo "${args[1]#cos://*/}  1234"; exit 0 ;;
    esac ;;
  cp) echo dumpbytes > "${args[2]}"; exit 0 ;;
  rm) touch "$COSCLI_LOG.rmdone"; exit "${COSCLI_RM_RC:-0}" ;;
esac
exit 96
'''


class Env:
    def __init__(self, root):
        self.root = root
        self.shims = root / "shims"
        self.shims.mkdir()
        self.dlog = root / "docker.log"
        self.clog = root / "coscli.log"
        self.dlog.write_text("")
        self.clog.write_text("")
        self.counts = root / "counts.txt"
        self.set_counts(dict(BEFORE, sensor_telemetry=160003, gps_position=1002))
        self.dump = root / NAME
        self.dump.write_bytes(b"x")
        self.cfg = root / "cos.yaml"
        self.cfg.write_text("x")
        self.rcfg = root / "cos-read.yaml"
        self.rcfg.write_text("x")
        _write_exe(self.shims / "docker", DOCKER_SHIM)
        _write_exe(self.shims / "coscli", COSCLI_SHIM)
        self.baseline = int(_psql("select coalesce(max(id),0) from backup_run"))

    def set_counts(self, c):
        self.counts.write_text("".join("%s|%d\n" % (t, c[t]) for t in TABLES))

    def add_run(self, key="daily/" + NAME, ok=True):
        _psql("insert into backup_run (started_at, finished_at, ok, kind, object_key, row_counts, row_counts_after) "
              "values (now(), now(), %s, 'daily', '%s', '%s'::jsonb, '%s'::jsonb)"
              % ("true" if ok else "false", key, json.dumps(BEFORE), json.dumps(AFTER)))

    def run(self, args, extra=None, bucket="test-bucket"):
        env = {"PATH": "%s:%s" % (self.shims, os.environ["PATH"]), "HOME": str(self.root),
               "DOCKER_LOG": str(self.dlog), "COSCLI_LOG": str(self.clog), "FAKE_COUNTS_FILE": str(self.counts)}
        if bucket is not None:
            env["COS_BUCKET"] = bucket
        env.update(extra or {})
        return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=120)

    def docker_calls(self):
        return [l for l in self.dlog.read_text().splitlines() if l]

    def coscli_calls(self):
        return [l for l in self.clog.read_text().splitlines() if l]


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    _psql("delete from backup_run where id > %d" % e.baseline)


def assert_cleaned(e):
    calls = e.docker_calls()
    assert any(c.startswith("rm -f lutetia-drill-") for c in calls), calls
    assert any(c.startswith("network rm lutetia-drill-net-") for c in calls), calls


def verdict_lines(r):
    return [l for l in r.stdout.splitlines() if " ≤ " in l]


def test_all_tables_within_bounds_exit_0_with_seven_ok_lines(env):
    env.add_run()
    r = env.run(["--file", str(env.dump)])
    assert r.returncode == 0, r.stdout + r.stderr
    lines = verdict_lines(r)
    assert len(lines) == 7 and all(l.endswith("OK") for l in lines)
    assert "sensor_telemetry 160000 ≤ 160003 ≤ 160008  OK" in lines
    assert "总耗时" in r.stdout
    assert_cleaned(env)


def test_boundaries_inclusive(env):
    env.add_run()
    env.set_counts(dict(BEFORE, sensor_telemetry=160000, gps_position=1004))  # 恰好等于前 / 后
    r = env.run(["--file", str(env.dump)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_table_below_before_fails_that_table(env):
    env.add_run()
    env.set_counts(dict(BEFORE, sensor_telemetry=159999, gps_position=1002))
    r = env.run(["--file", str(env.dump)])
    assert r.returncode != 0
    lines = verdict_lines(r)
    assert len(lines) == 7
    assert "sensor_telemetry 160000 ≤ 159999 ≤ 160008  FAIL" in lines
    assert sum(l.endswith("FAIL") for l in lines) == 1
    assert_cleaned(env)


def test_table_above_after_fails(env):
    env.add_run()
    env.set_counts(dict(BEFORE, sensor_telemetry=160009, gps_position=1002))
    r = env.run(["--file", str(env.dump)])
    assert r.returncode != 0
    assert "sensor_telemetry 160000 ≤ 160009 ≤ 160008  FAIL" in verdict_lines(r)


def test_no_matching_backup_run_row_fails_with_message_and_starts_nothing(env):
    env.add_run(key="daily/lutetia-20990202T000000Z.dump")  # 别的文件
    r = env.run(["--file", str(env.dump)])
    assert r.returncode != 0
    assert "backup_run" in r.stderr and NAME in r.stderr
    assert not any(c.startswith("run ") for c in env.docker_calls())  # 没起容器


def test_failed_run_row_does_not_match(env):
    env.add_run(ok=False)
    r = env.run(["--file", str(env.dump)])
    assert r.returncode != 0 and "backup_run" in r.stderr


def test_sunday_weekly_key_matches_by_basename(env):
    env.add_run(key="weekly/" + NAME)
    r = env.run(["--file", str(env.dump)])
    assert r.returncode == 0, r.stdout + r.stderr


def test_percent_in_object_key_not_treated_as_wildcard(env):
    env.add_run(key="daily/lutetia-20990101T00000%Z.dump")
    r = env.run(["--file", str(env.dump)])
    assert r.returncode != 0 and "backup_run" in r.stderr


def test_restore_failure_cleans_up_and_fails(env):
    env.add_run()
    r = env.run(["--file", str(env.dump)], extra={"FAKE_RESTORE_RC": "1"})
    assert r.returncode != 0 and "pg_restore" in r.stderr
    assert verdict_lines(r) == []
    assert_cleaned(env)


def test_container_start_failure_cleans_up_network(env):
    env.add_run()
    r = env.run(["--file", str(env.dump)], extra={"FAKE_RUN_RC": "1"})
    assert r.returncode != 0
    assert any(c.startswith("network rm lutetia-drill-net-") for c in env.docker_calls())


def test_container_has_no_volume_and_password_not_printed(env):
    env.add_run()
    r = env.run(["--file", str(env.dump)])
    assert r.returncode == 0, r.stderr
    (run_call,) = [c for c in env.docker_calls() if c.startswith("run ")]
    assert "-v " not in run_call and "--volume" not in run_call and "--mount" not in run_call
    assert "--network lutetia-drill-net-" in run_call and "postgres:16-alpine" in run_call
    assert "-e POSTGRES_PASSWORD" in run_call and "POSTGRES_PASSWORD=" not in run_call  # 值不进 argv
    assert SECRET_PW_HINT + "=" not in r.stdout + r.stderr


def test_neither_file_nor_from_cos_fails(env):
    r = env.run([])
    assert r.returncode == 2
    assert "--file" in r.stderr and "--from-cos" in r.stderr
    assert env.docker_calls() == []


def test_missing_file_fails(env):
    env.add_run()
    r = env.run(["--file", str(env.root / "nope.dump")])
    assert r.returncode != 0 and "不存在" in r.stderr


def test_from_cos_requires_read_config(env):
    r = env.run(["--from-cos"])
    assert r.returncode != 0 and "COSCLI_READ_CONFIG" in r.stderr
    r = env.run(["--from-cos"], extra={"COSCLI_READ_CONFIG": str(env.root / "nope.yaml")})
    assert r.returncode != 0 and "不存在" in r.stderr
    assert env.coscli_calls() == []


def test_from_cos_downloads_newest_daily_with_read_config(env):
    env.add_run()
    r = env.run(["--from-cos"], extra={"COSCLI_READ_CONFIG": str(env.cfg)})
    assert r.returncode == 0, r.stdout + r.stderr
    calls = env.coscli_calls()
    assert calls[0] == "-c %s ls cos://test-bucket/daily/" % env.cfg
    assert calls[1].startswith("-c %s cp cos://test-bucket/daily/%s " % (env.cfg, NAME))
    assert len(calls) == 2  # 没有删除
    assert len(verdict_lines(r)) == 7


def _delete_run(env, extra=None, with_read=True):
    x = {"COSCLI_CONFIG": str(env.cfg)}
    if with_read:
        x["COSCLI_READ_CONFIG"] = str(env.rcfg)
    x.update(extra or {})
    return env.run(["--file", str(env.dump), "--check-delete-denied"], extra=x)


def _rm_calls(env):
    return [c for c in env.coscli_calls() if " rm " in " %s " % c]


@pytest.mark.parametrize("rm_rc", ["0", "1"])
def test_delete_denied_pass_when_object_still_present_whatever_rm_rc(env, rm_rc):
    env.add_run()
    r = _delete_run(env, {"COSCLI_RM_RC": rm_rc})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "delete-denied PASS" in r.stdout
    assert _rm_calls(env) == ["-c %s rm -f cos://test-bucket/daily/%s" % (env.cfg, NAME)]
    ls = [c for c in env.coscli_calls() if " ls " in " %s " % c]
    assert ls == ["-c %s ls cos://test-bucket/daily/%s" % (env.rcfg, NAME)] * 2  # 前后各一次，都用读配置


def test_delete_object_gone_after_rm_is_loud_fail(env):
    env.add_run()
    r = _delete_run(env, {"FAKE_RM_DELETES": "1"})
    assert r.returncode != 0
    assert "upload key can delete — fix the key policy now" in r.stderr
    assert "PASS" not in r.stdout
    assert_cleaned(env)


def test_delete_post_check_error_is_cannot_confirm_fail(env):
    env.add_run()
    r = _delete_run(env, {"FAKE_LS_POST_ERR": "1", "COSCLI_RM_RC": "1"})
    assert r.returncode != 0
    assert "cannot confirm" in r.stderr
    assert "PASS" not in r.stdout


@pytest.mark.parametrize("extra", [{"FAKE_OBJECT_ABSENT": "1"}, {"FAKE_LS_PRE_ERR": "1"}])
def test_delete_precheck_object_missing_or_ls_error_fails_without_rm(env, extra):
    env.add_run()
    r = _delete_run(env, extra)
    assert r.returncode != 0 and "PASS" not in r.stdout
    assert _rm_calls(env) == []


def test_delete_check_requires_read_config_before_any_rm(env):
    env.add_run()
    r = _delete_run(env, with_read=False)
    assert r.returncode != 0 and "COSCLI_READ_CONFIG" in r.stderr
    assert env.coscli_calls() == []
    assert not any(c.startswith("run ") for c in env.docker_calls())


def test_delete_not_attempted_without_flag(env):
    env.add_run()
    r = env.run(["--file", str(env.dump)])
    assert r.returncode == 0
    assert _rm_calls(env) == []


def test_pg_restore_skips_privileges_and_owner(env):
    env.add_run()
    r = env.run(["--file", str(env.dump)])
    assert r.returncode == 0, r.stdout + r.stderr
    (call,) = [c for c in env.docker_calls() if " pg_restore " in " %s " % c]
    assert "--no-privileges" in call.split() and "--no-owner" in call.split()
