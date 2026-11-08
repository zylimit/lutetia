# risk: high
"""deploy/backup.sh 行为回归（Task 6.1）：PATH 垫片替换 docker / coscli / date，真跑脚本，真写合成库 backup_run。

断言依据 DEV-PLAN Task 6.1 与 Business Context，不照抄脚本实现：
成功与失败都要留一行；周日传 daily/ 再传 weekly/；本地只留 2 份；失败原因不含凭据。
只在 DATABASE_URL 指向合成库（:15433）且容器 lutetia-pg 在跑时才执行，否则 skip。
"""
import json
import os
import shutil
import signal
import stat
import subprocess
import time
from pathlib import Path

import pytest

from lutetia.config import load_dotenv

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
CONTAINER = "lutetia-pg"
REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "deploy" / "backup.sh"
REAL_DOCKER = shutil.which("docker") or ""
SECRET = "SEKRET-VALUE-9f3a71c2"
COUNT_KEYS = {"device", "gps_position", "sensor_telemetry", "sensor_attribute",
              "api_call", "poi", "poi_cable_segment"}


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


class Env:
    def __init__(self, root):
        self.root = root
        self.shims = root / "shims"
        self.shims.mkdir()
        self.backup_dir = root / "bk"
        self.log = root / "coscli.log"
        self.log.write_text("")
        _write_exe(self.shims / "docker",
                   '#!/bin/bash\n[ "$1 $2 $3 $4" = "compose exec -T db" ] || '
                   '{ echo "unexpected docker args: $*" >&2; exit 97; }\n'
                   'shift 4\nif [ -n "$FAKE_DUMP_SLEEP" ] && [[ " $* " == *" pg_dump "* ]]; then\n'
                   '  echo started > "$FAKE_DUMP_MARK"; exec sleep "$FAKE_DUMP_SLEEP"\nfi\n'
                   'exec "%s" exec -i %s "$@"\n' % (REAL_DOCKER, CONTAINER))
        _write_exe(self.shims / "date",
                   '#!/bin/bash\nfor a in "$@"; do [ "$a" = "+%u" ] && { echo "$FAKE_DOW"; exit 0; }; done\n'
                   'exec /bin/date "$@"\n')
        self.baseline = int(_psql("select coalesce(max(id),0) from backup_run"))

    def add_coscli(self):
        _write_exe(self.shims / "coscli",
                   '#!/bin/bash\necho "$*" >> "$COSCLI_LOG"\n'
                   'if [ -n "$COSCLI_FAIL_MATCH" ] && [[ "$*" == *"$COSCLI_FAIL_MATCH"* ]]; then exit 7; fi\nexit 0\n')

    def run(self, args=(), dow="3", bucket="test-bucket", extra=None):
        env = {"PATH": "%s:%s" % (self.shims, os.environ["PATH"]), "HOME": str(self.root),
               "BACKUP_DIR": str(self.backup_dir), "FAKE_DOW": dow, "COSCLI_LOG": str(self.log),
               "COSCLI_SECRET_KEY": SECRET}
        if bucket is not None:
            env["COS_BUCKET"] = bucket
        env.update(extra or {})
        return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=120)

    def rows(self):
        out = _psql("select coalesce(json_agg(r order by id), '[]'::json) from (select id, kind, ok, "
                    "object_key, bytes, sha256, row_counts, row_counts_after, error from backup_run where id > %d) r" % self.baseline)
        return json.loads(out)

    def coscli_calls(self):
        return [l for l in self.log.read_text().splitlines() if l]


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    yield e
    _psql("delete from backup_run where id > %d" % e.baseline)


def dumps(e):
    return sorted(p.name for p in e.backup_dir.glob("lutetia-*.dump"))


def test_local_only_records_ok_row_without_upload(env):
    env.add_coscli()
    r = env.run(["--local-only"], bucket=None)
    assert r.returncode == 0, r.stderr
    (row,) = env.rows()
    assert row["ok"] is True and row["object_key"] is None and row["error"] is None
    assert row["bytes"] > 0
    assert len(row["sha256"]) == 64 and int(row["sha256"], 16) >= 0
    assert set(row["row_counts"]) == COUNT_KEYS
    assert set(row["row_counts_after"]) == COUNT_KEYS
    assert all(row["row_counts_after"][k] >= row["row_counts"][k] for k in COUNT_KEYS)
    assert env.coscli_calls() == []
    (name,) = dumps(env)
    assert (env.backup_dir / name).stat().st_size == row["bytes"]


def test_weekday_uploads_once_to_daily(env):
    env.add_coscli()
    r = env.run(dow="3")
    assert r.returncode == 0, r.stderr
    (name,) = dumps(env)
    calls = env.coscli_calls()
    assert len(calls) == 1
    assert calls[0].startswith("cp ") and calls[0].endswith("cos://test-bucket/daily/" + name)
    (row,) = env.rows()
    assert (row["kind"], row["ok"], row["object_key"]) == ("daily", True, "daily/" + name)


def test_sunday_uploads_daily_then_weekly_same_file(env):
    env.add_coscli()
    r = env.run(dow="7")
    assert r.returncode == 0, r.stderr
    (name,) = dumps(env)
    calls = env.coscli_calls()
    assert len(calls) == 2
    assert calls[0].endswith("cos://test-bucket/daily/" + name)
    assert calls[1].endswith("cos://test-bucket/weekly/" + name)
    assert calls[0].split()[1] == calls[1].split()[1]  # 同一个本地文件
    (row,) = env.rows()
    assert (row["kind"], row["ok"]) == ("weekly", True)
    assert row["object_key"] == "weekly/" + name


def test_upload_failure_records_failed_row_without_secret(env):
    env.add_coscli()
    r = env.run(extra={"COSCLI_FAIL_MATCH": "cos://"})
    assert r.returncode != 0
    (row,) = env.rows()
    assert row["ok"] is False and row["object_key"] is None
    assert row["error"] and "upload-daily" in row["error"]
    assert SECRET not in json.dumps(row) and SECRET not in r.stdout + r.stderr


def test_sunday_weekly_upload_failure_is_whole_run_failure(env):
    env.add_coscli()
    r = env.run(dow="7", extra={"COSCLI_FAIL_MATCH": "/weekly/"})
    assert r.returncode != 0
    assert len(env.coscli_calls()) == 2
    (row,) = env.rows()
    assert row["ok"] is False and row["object_key"] is None  # 不能报 daily 成功后记 ok
    assert "upload-weekly" in row["error"]


def test_missing_bucket_fails_without_upload(env):
    env.add_coscli()
    r = env.run(bucket=None)
    assert r.returncode != 0
    assert env.coscli_calls() == []
    (row,) = env.rows()
    assert row["ok"] is False and "config" in row["error"]
    assert dumps(env) == []  # 配置错在 dump 之前就停


def test_unknown_arg_exits_2_without_row(env):
    r = env.run(["--bogus"])
    assert r.returncode == 2
    assert env.rows() == []


def test_local_retention_keeps_two_newest_and_spares_other_files(env):
    env.add_coscli()
    env.backup_dir.mkdir()
    now = time.time()
    old = ["lutetia-20200101T000000Z.dump", "lutetia-20200102T000000Z.dump", "lutetia-20200103T000000Z.dump"]
    for i, n in enumerate(old):
        p = env.backup_dir / n
        p.write_bytes(b"x")
        os.utime(p, (now - 1000 + i, now - 1000 + i))
    other = env.backup_dir / "notes.txt"
    other.write_text("keep me")
    r = env.run(["--local-only"], bucket=None)
    assert r.returncode == 0, r.stderr
    left = dumps(env)
    assert len(left) == 2
    assert old[2] in left and old[0] not in left and old[1] not in left
    assert other.read_text() == "keep me"


def test_no_coscli_binary_fails_at_config_stage(env):
    # 不放 coscli 垫片；若主机恰好装了真 coscli 则此用例无意义
    if shutil.which("coscli"):
        pytest.skip("real coscli on PATH")
    r = env.run()
    assert r.returncode != 0
    (row,) = env.rows()
    assert row["ok"] is False and "config" in row["error"]


def test_sigterm_during_dump_records_failed_row_and_cleans_partial(env):
    env.add_coscli()
    mark = env.root / "dump.mark"
    full = {"PATH": "%s:%s" % (env.shims, os.environ["PATH"]), "HOME": str(env.root),
            "BACKUP_DIR": str(env.backup_dir), "FAKE_DOW": "3", "COSCLI_LOG": str(env.log),
            "FAKE_DUMP_SLEEP": "60", "FAKE_DUMP_MARK": str(mark), "COS_BUCKET": "test-bucket"}
    # 新会话 + killpg：与 systemd 对整个 cgroup 发 SIGTERM 等价（bash 要等前台子进程结束才跑 trap）
    p = subprocess.Popen(["bash", str(SCRIPT)], env=full, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, start_new_session=True)
    try:
        for _ in range(200):
            if mark.exists():
                break
            time.sleep(0.1)
        assert mark.exists(), "pg_dump 垫片没起来"
        os.killpg(p.pid, signal.SIGTERM)
        out, err = p.communicate(timeout=30)
    finally:
        if p.poll() is None:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
    assert p.returncode == 143
    (row,) = env.rows()
    assert row["ok"] is False and row["object_key"] is None
    assert "signal=TERM" in row["error"]
    assert list(env.backup_dir.glob("*.partial")) == []
    assert "备份完成" not in out + err


def test_coscli_config_path_passed_with_dash_c(env):
    env.add_coscli()
    cfg = env.root / "cos.yaml"
    cfg.write_text("x")
    r = env.run(extra={"COSCLI_CONFIG": str(cfg)})
    assert r.returncode == 0, r.stderr
    (call,) = env.coscli_calls()
    assert call.startswith("-c %s cp " % cfg)


def test_coscli_config_missing_file_fails_at_config_stage(env):
    env.add_coscli()
    r = env.run(extra={"COSCLI_CONFIG": str(env.root / "nope.yaml")})
    assert r.returncode != 0
    (row,) = env.rows()
    assert row["ok"] is False and "stage=config" in row["error"] and "配置文件不存在" in row["error"]
    assert env.coscli_calls() == [] and dumps(env) == []
