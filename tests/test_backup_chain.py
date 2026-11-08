# risk: high
"""Phase 6 跨 Task 链路（DFX RS-1）：backup.sh 真 dump -> backup_summary / anomalies 读到 -> restore-drill.sh 真容器恢复。

断言依据 DEV-PLAN Phase 6 与 Business Context：备份只有恢复得出来才算数，恢复行数须落在 backup_run 记的前后区间内。
docker 垫片只转发 `compose exec -T db ...` 到合成库容器 lutetia-pg；演练用的临时容器走真 docker（postgres:16-alpine）。
合成数据全用 test-chain 前缀并在 finally 里精确删除；DATABASE_URL 非合成库（:15433）或无 docker 则 skip。
"""
import asyncio
import os
import shutil
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from lutetia.config import load_dotenv
from lutetia.db import Database
from lutetia.web import anomalies

load_dotenv()
DB_URL = os.environ.get("DATABASE_URL", "")
CONTAINER = "lutetia-pg"
REPO = Path(__file__).resolve().parent.parent
REAL_DOCKER = shutil.which("docker") or ""
TAG = "test-chain"


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
    if subprocess.run([REAL_DOCKER, "exec", CONTAINER, "true"], capture_output=True).returncode != 0:
        pytest.skip("container lutetia-pg not running")
    if _psql("select to_regclass('backup_run')") != "backup_run":
        pytest.skip("backup_run table missing (migrate first)")
    if subprocess.run([REAL_DOCKER, "image", "inspect", "postgres:16-alpine"], capture_output=True).returncode != 0:
        pytest.skip("postgres:16-alpine image not present locally")


def _exe(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def world(tmp_path):
    shims = tmp_path / "shims"
    shims.mkdir()
    # backup.sh 只用 compose exec；演练脚本的 compose 部分同样转发，其余（run/exec/network/rm）直通真 docker
    _exe(shims / "docker",
         '#!/bin/bash\nif [ "$1 $2 $3 $4" = "compose exec -T db" ]; then shift 4; exec "%s" exec -i %s "$@"; fi\n'
         'exec "%s" "$@"\n' % (REAL_DOCKER, CONTAINER, REAL_DOCKER))
    baseline = int(_psql("select coalesce(max(id),0) from backup_run"))
    _psql("insert into device (source, device_id, name) values ('%s', '%s-1', 'chain'), ('%s', '%s-2', 'chain')"
          % (TAG, TAG, TAG, TAG))
    _psql("insert into gps_position (device_id, update_time, origin, lat, lon) values "
          "('%s-1', now() - interval '2 min', '%s', 48.1, 2.3), ('%s-1', now() - interval '1 min', '%s', 48.2, 2.4)"
          % (TAG, TAG, TAG, TAG))
    _psql("insert into poi (poi_no, content_sha, raw_sha) values ('TEST-CHAIN-1', 'c', 'r')")
    env = {"PATH": "%s:%s" % (shims, os.environ["PATH"]), "HOME": str(tmp_path), "BACKUP_DIR": str(tmp_path / "bk")}
    yield {"env": env, "dir": tmp_path / "bk", "baseline": baseline}
    _psql("delete from poi where poi_no = 'TEST-CHAIN-1'")
    _psql("delete from gps_position where device_id like '%s-%%'" % TAG)
    _psql("delete from device where source = '%s'" % TAG)
    _psql("delete from backup_run where id > %d" % baseline)


def _backup(w):
    r = subprocess.run(["bash", str(REPO / "deploy" / "backup.sh"), "--local-only"], env=w["env"],
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr
    (dump,) = list(w["dir"].glob("lutetia-*.dump"))
    return dump


def _drill(w, dump):
    return subprocess.run(["bash", str(REPO / "deploy" / "restore-drill.sh"), "--file", str(dump)], env=w["env"],
                          capture_output=True, text=True, timeout=300)


def _leftovers():
    c = subprocess.run([REAL_DOCKER, "ps", "-a", "--filter", "name=lutetia-drill", "--format", "{{.Names}}"],
                       capture_output=True, text=True).stdout.split()
    n = [x for x in subprocess.run([REAL_DOCKER, "network", "ls", "--format", "{{.Name}}"],
                                   capture_output=True, text=True).stdout.split() if x.startswith("lutetia-drill")]
    return c + n


def _summary():
    async def go():
        d = Database(DB_URL)
        await d.connect()
        try:
            return await d.backup_summary()
        finally:
            await d.close()
    return asyncio.run(go())


def test_backup_to_dashboard_to_restore_chain(world):
    dump = _backup(world)
    assert dump.stat().st_size > 0
    row = _psql("select id || '|' || ok || '|' || to_char(finished_at at time zone 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.US') "
                "from backup_run where id > %d order by id desc limit 1" % world["baseline"])
    rid, ok, fin = row.split("|")
    assert ok == "true"
    # 看板侧：last_ok_at 即这行的 finished_at，最近一次成功，且不产生 backup 异常
    s = _summary()
    assert s["latest_ok"] is True
    assert s["last_ok_at"].astimezone(timezone.utc).replace(tzinfo=None) == datetime.fromisoformat(fin)
    now = s["last_ok_at"] + timedelta(minutes=5)
    assert [i for i in anomalies.compute(now, [], [], [], None, [], 1400, 3.4, backup=s) if i["kind"] == "backup"] == []

    # 只 --local-only 的行 object_key 为空：演练按文件 sha256 匹配，照样能演练；真容器恢复真 dump
    assert _psql("select object_key is null from backup_run where id = %s" % rid) == "t"
    r = _drill(world, dump)
    assert r.returncode == 0, r.stdout + r.stderr
    ok_lines = [l for l in r.stdout.splitlines() if l.endswith("  OK")]
    assert len(ok_lines) == 7, r.stdout
    assert "FAIL" not in r.stdout
    assert any(l.startswith("device ") and "≤ 2 ≤" in l for l in ok_lines)  # 合成设备确实被恢复出来
    assert _leftovers() == []


def test_modified_dump_fails_sha256_match_and_starts_no_container(world):
    dump = _backup(world)
    data = bytearray(dump.read_bytes())
    data[-1] ^= 0x01  # 改一个字节
    dump.write_bytes(bytes(data))
    r = _drill(world, dump)
    assert r.returncode == 1 and "sha256 对不上" in r.stderr
    assert _leftovers() == []
