# risk: high
"""deploy/host-deploy.sh 前三步行为回归（Task 7.3，L-4）。

断言依据 DEV-PLAN Phase 7 / TODO #102 / Pinned「凭据零入日志」，不照抄脚本：
  1 步：git pull 之后脚本自己被更新则用新版重跑，且只重跑一次；没变不重跑；
  2 步：.env 必填键缺失 / 为空 / DATABASE_RO_PASSWORD / SESSION_SECRET 含非字母数字时非零退出，任何输出都不含密钥值；
  3 步：容器等到 healthy 才往下走，等不到就在 HEALTH_WAIT_SEC 后非零退出并点名服务。
PATH 垫片替换 git / docker / sudo / sha256sum / sleep / nginx / systemctl / certbot / curl，一律不碰真实命令。
假 sudo 恒返回 42 且不执行任何东西：脚本走到第 4 步第一次 sudo 就停，rc==42 即「前三步全过」。
"""
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "deploy" / "host-deploy.sh"
STOP_RC = 42  # fake sudo exit code: reached step 4

SHIMS = {
    "git": r'''#!/bin/bash
echo "git $*" >> "$FAKE_STATE/calls.log"
[ "$1 $2" = "pull --ff-only" ] || { echo "UNEXPECTED git $*" >> "$FAKE_STATE/calls.log"; exit 97; }
[ -e "$FAKE_STATE/git-fail" ] && { echo "fatal: not possible to fast-forward" >&2; exit 1; }
mode=$(cat "$FAKE_STATE/git-mode" 2>/dev/null)
n=$(grep -c '^git pull' "$FAKE_STATE/calls.log")
if [ "$mode" = always ] || { [ "$mode" = once ] && [ ! -e "$FAKE_STATE/rewritten" ]; }; then
  touch "$FAKE_STATE/rewritten"
  tmp="$FAKE_TARGET.new"
  sed 's/\[2\/8\]/[2\/8 v2]/' "$FAKE_TARGET" > "$tmp"
  echo "# rev $n" >> "$tmp"
  chmod +x "$tmp"
  mv "$tmp" "$FAKE_TARGET"   # 与真 git 一样换 inode，正在读旧文件的 bash 不受影响
fi
exit 0
''',
    "docker": r'''#!/bin/bash
echo "docker $*" >> "$FAKE_STATE/calls.log"
case "$1 $2" in
  "compose up") exit 0 ;;
  "compose ps")
    if [ "$3" = "-q" ]; then
      svc=$4
      k=$(cat "$FAKE_STATE/ps-empty-$svc" 2>/dev/null || echo 0)
      c=$(( $(cat "$FAKE_STATE/ps-count-$svc" 2>/dev/null || echo 0) + 1 ))
      echo $c > "$FAKE_STATE/ps-count-$svc"
      if [ "$k" = all ] || [ "$c" -le "$k" ]; then exit 0; fi
      echo "cid-$svc"
    fi
    exit 0 ;;
  "inspect -f")
    svc=${4#cid-}
    after=$(cat "$FAKE_STATE/healthy-after-$svc" 2>/dev/null || echo 1)
    c=$(( $(cat "$FAKE_STATE/n-$svc" 2>/dev/null || echo 0) + 1 ))
    echo $c > "$FAKE_STATE/n-$svc"
    if [ "$after" != never ] && [ "$c" -ge "$after" ]; then echo healthy; else echo starting; fi
    exit 0 ;;
esac
echo "UNEXPECTED docker $*" >> "$FAKE_STATE/calls.log"
exit 97
''',
    "sudo": '#!/bin/bash\necho "sudo $*" >> "$FAKE_STATE/calls.log"\nexit 42\n',
    "sha256sum": '#!%s\nimport hashlib, sys\n'
                 'for p in sys.argv[1:]:\n'
                 '    print(hashlib.sha256(open(p, "rb").read()).hexdigest() + "  " + p)\n' % sys.executable,
    "sleep": '#!/bin/bash\nexec /bin/sleep 0.1\n',
}
for _n in ("nginx", "systemctl", "certbot", "curl"):
    SHIMS[_n] = '#!/bin/bash\necho "%s $*" >> "$FAKE_STATE/calls.log"\nexit 0\n' % _n


def _exe(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


class Sandbox:
    def __init__(self, root):
        self.root = root
        self.repo = root / "repo"
        (self.repo / "deploy").mkdir(parents=True)
        self.script = self.repo / "deploy" / "host-deploy.sh"
        self.script.write_bytes(SRC.read_bytes())
        self.state = root / "state"
        self.state.mkdir()
        (self.state / "calls.log").write_text("")
        shims = root / "shims"
        shims.mkdir()
        for name, body in SHIMS.items():
            _exe(shims / name, body)
        self.shims = shims
        # 值在每次测试运行时随机生成，不写死
        self.secrets = {k: secrets.token_hex(12) for k in ("DASHBOARD_PWD", "API_KEY", "PUSH_PATH", "DATABASE_RO_PASSWORD", "SESSION_SECRET")}
        self.write_env()

    def write_env(self, overrides=None, drop=()):
        vals = dict(self.secrets)
        vals.update(overrides or {})
        lines = ["%s=%s" % (k, v) for k, v in vals.items() if k not in drop]
        (self.repo / ".env").write_text("\n".join(lines) + "\n")

    def set(self, name, value):
        (self.state / name).write_text(str(value))

    def calls(self):
        return (self.state / "calls.log").read_text().splitlines()

    def run(self, mode="root", health_wait="2", extra=None):
        env = {"PATH": "%s:/usr/bin:/bin" % self.shims, "HOME": str(self.root),
               "FAKE_STATE": str(self.state), "FAKE_TARGET": str(self.script), "HEALTH_WAIT_SEC": health_wait}
        env.update(extra or {})
        if mode == "root":      # 仓库根，相对路径
            cmd, cwd = ["bash", "deploy/host-deploy.sh"], self.repo
        elif mode == "inside":  # 副本目录内部
            cmd, cwd = ["bash", "host-deploy.sh"], self.repo / "deploy"
        else:                   # 无关目录，绝对路径
            cmd, cwd = ["bash", str(self.script)], self.root
        r = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=60)
        assert not any(c.startswith("UNEXPECTED") for c in self.calls()), self.calls()
        return r

    def count(self, prefix):
        return sum(1 for c in self.calls() if c.startswith(prefix))


@pytest.fixture
def sb(tmp_path):
    return Sandbox(tmp_path)


def assert_no_secret(sb, r, *values):
    for v in values or sb.secrets.values():
        assert v not in r.stdout and v not in r.stderr


# ---------- 第 2 步：.env 检查，凭据零入日志 ----------

def test_missing_env_file_fails_before_docker(sb):
    (sb.repo / ".env").unlink()
    r = sb.run()
    assert r.returncode != 0
    assert sb.count("docker") == 0


def _bad_values():
    # 前后缀随机，中间放危险字符；参数化在收集期取值，值不写死
    return [
        pytest.param(lambda t: t + "/" + t, id="slash"),
        pytest.param(lambda t: t + "@" + t, id="at"),
        pytest.param(lambda t: '"' + t + '"', id="double-quoted"),
        pytest.param(lambda t: "'" + t + "'", id="single-quoted"),
        pytest.param(lambda t: t + "#" + t, id="hash"),
        pytest.param(lambda t: t + " " + t, id="space"),
    ]


@pytest.mark.parametrize("make", _bad_values())
def test_ro_password_with_unsafe_chars_rejected_without_echo(sb, make):
    bad = make(secrets.token_hex(8))
    sb.write_env({"DATABASE_RO_PASSWORD": bad})
    r = sb.run()
    assert r.returncode != 0
    assert "[2/8" in r.stdout
    assert "DATABASE_RO_PASSWORD" in r.stdout + r.stderr  # 点名键，不点值
    assert bad not in r.stdout and bad not in r.stderr
    core = bad.strip("'\"")
    assert core not in r.stdout and core not in r.stderr
    assert sb.count("docker") == 0 and "[3/8" not in r.stdout


@pytest.mark.parametrize("make", _bad_values())
def test_session_secret_with_unsafe_chars_rejected_without_echo(sb, make):
    bad = make(secrets.token_hex(8))
    sb.write_env({"SESSION_SECRET": bad})
    r = sb.run()
    assert r.returncode != 0
    assert "[2/8" in r.stdout
    assert "SESSION_SECRET" in r.stdout + r.stderr
    core = bad.strip("'\"")
    for v in (bad, core):
        assert v not in r.stdout and v not in r.stderr
    assert sb.count("docker") == 0 and "[3/8" not in r.stdout


@pytest.mark.parametrize("how", ["missing", "empty"])
def test_ro_password_missing_or_empty_rejected(sb, how):
    if how == "missing":
        sb.write_env(drop=("DATABASE_RO_PASSWORD",))
    else:
        sb.write_env({"DATABASE_RO_PASSWORD": ""})
    r = sb.run()
    assert r.returncode != 0
    assert "DATABASE_RO_PASSWORD" in r.stdout + r.stderr
    assert sb.count("docker") == 0
    assert_no_secret(sb, r)


@pytest.mark.parametrize("key", ["DASHBOARD_PWD", "API_KEY", "PUSH_PATH", "SESSION_SECRET"])
@pytest.mark.parametrize("how", ["missing", "empty"])
def test_other_required_keys_rejected_without_echo(sb, key, how):
    if how == "missing":
        sb.write_env(drop=(key,))
    else:
        sb.write_env({key: ""})
    r = sb.run()
    assert r.returncode != 0
    assert key in r.stdout + r.stderr
    assert sb.count("docker") == 0
    assert_no_secret(sb, r)


def test_valid_env_passes_steps_1_to_3_and_prints_no_secret(sb):
    r = sb.run()
    assert r.returncode == STOP_RC, r.stdout + r.stderr  # 第 4 步第一次 sudo 才停
    assert "[4/8" in r.stdout
    assert_no_secret(sb, r)
    assert "docker compose up -d --build" in sb.calls()
    assert sb.count("git pull --ff-only") == 1
    assert not any(c.startswith(("nginx", "systemctl", "certbot", "curl")) for c in sb.calls())


# ---------- 第 3 步：wait_healthy ----------

@pytest.mark.parametrize("n", [1, 3])
def test_waits_until_collector_turns_healthy(sb, n):
    sb.set("healthy-after-collector", n)
    r = sb.run(health_wait="60")  # success path: a generous budget, so a loaded machine (parallel runs) cannot time it out
    assert r.returncode == STOP_RC, r.stdout + r.stderr
    assert "collector healthy" in r.stdout and "web healthy" in r.stdout
    assert sb.count("docker inspect") == n + 1  # collector 第 n 次变 healthy 即停止查询，web 一次


def test_collector_never_healthy_times_out_and_names_service(sb):
    sb.set("healthy-after-collector", "never")
    r = sb.run(health_wait="10")
    assert r.returncode != 0 and r.returncode != STOP_RC
    assert "collector" in r.stderr
    assert "[4/8" not in r.stdout
    assert sb.count("sudo") == 0
    assert sb.count("docker inspect") >= 2  # 确实在轮询而不是一次就放弃
    assert_no_secret(sb, r)


def test_web_never_healthy_names_web(sb):
    sb.set("healthy-after-web", "never")
    r = sb.run(health_wait="2")
    assert r.returncode != 0 and r.returncode != STOP_RC
    assert "collector healthy" in r.stdout
    assert "web" in r.stderr and "collector" not in r.stderr
    assert sb.count("sudo") == 0


def test_empty_ps_q_does_not_crash_and_times_out(sb):
    sb.set("ps-empty-collector", "all")
    r = sb.run(health_wait="10")
    assert r.returncode != 0 and r.returncode != STOP_RC
    assert "collector" in r.stderr
    assert sb.count("docker inspect") == 0  # 没有容器 id 就不该去 inspect 空串
    assert sb.count("docker compose ps -q collector") >= 2
    assert sb.count("sudo") == 0


def test_container_appearing_late_is_still_waited_for(sb):
    sb.set("ps-empty-collector", 3)  # 前 3 次 ps -q 返回空，之后才有容器
    r = sb.run(health_wait="60")
    assert r.returncode == STOP_RC, r.stdout + r.stderr
    assert "collector healthy" in r.stdout


# ---------- 第 1 步：自更新重跑 ----------

@pytest.mark.parametrize("mode", ["root", "inside", "elsewhere"])
def test_self_update_reruns_new_version_exactly_once(sb, mode):
    sb.set("git-mode", "once")
    r = sb.run(mode=mode)
    assert r.returncode == STOP_RC, r.stdout + r.stderr
    assert r.stdout.count("host-deploy.sh 已更新") == 1
    assert r.stdout.count("[2/8 v2]") == 1  # 新版本跑了第 2 步
    assert "[2/8]" not in r.stdout          # 旧版本没有继续往下跑
    assert r.stdout.count("[1/8]") == 2     # 第 1 步：旧版一次 + 新版一次
    assert sb.count("git pull --ff-only") == 2
    assert sb.count("docker compose up") == 1  # 部署动作只发生一次
    assert_no_secret(sb, r)


@pytest.mark.parametrize("mode", ["root", "inside", "elsewhere"])
def test_self_update_does_not_loop_when_every_pull_rewrites(sb, mode):
    sb.set("git-mode", "always")  # 最坏情况：每次 pull 脚本都变
    r = sb.run(mode=mode)
    assert r.returncode == STOP_RC, r.stdout + r.stderr
    assert r.stdout.count("host-deploy.sh 已更新") == 1
    assert sb.count("git pull --ff-only") == 2
    assert sb.count("docker compose up") == 1


@pytest.mark.parametrize("mode", ["root", "inside", "elsewhere"])
def test_unchanged_script_is_not_rerun(sb, mode):
    r = sb.run(mode=mode)
    assert r.returncode == STOP_RC, r.stdout + r.stderr
    assert "已更新" not in r.stdout
    assert r.stdout.count("[1/8]") == 1
    assert sb.count("git pull --ff-only") == 1


def test_git_pull_failure_stops_before_env_check(sb):
    (sb.state / "git-fail").write_text("")
    r = sb.run()
    assert r.returncode != 0 and r.returncode != STOP_RC
    assert "[2/8" not in r.stdout
    assert sb.count("docker") == 0
