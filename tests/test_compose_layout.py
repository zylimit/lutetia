# risk: high
"""Phase 7 Task 7.3: docker-compose.yml 的最小权限布局（静态文本断言，不引 yaml 依赖）。
web 无整包环境文件、用只读角色连库、拿不到厂家账号；collector 带只读角色密码；两个发布端口只绑回环。"""
import re
from pathlib import Path

TEXT = (Path(__file__).resolve().parent.parent / "docker-compose.yml").read_text(encoding="utf-8")


def service_block(name):
    m = re.search(r"^  %s:\n((?:(?:    .*)?\n)+)" % name, TEXT, re.M)
    assert m, "service %s missing" % name
    return "\n".join(l for l in m.group(1).splitlines() if not l.lstrip().startswith("#"))


def test_three_services_same_image():
    assert re.findall(r"^  ([a-z]+):$", TEXT.split("\nvolumes:")[0], re.M) == ["db", "collector", "web"]
    imgs = re.findall(r"image: (lutetia:\S+)", service_block("collector") + service_block("web"))
    assert len(imgs) == 2 and imgs[0] == imgs[1]


def test_web_has_no_env_file_and_no_vendor_secrets():
    web = service_block("web")
    assert "env_file" not in web
    for key in ("GPS51_USER", "GPS51_PWD", "DINGTEK_USER", "DINGTEK_PWD", "POSTGRES_PASSWORD", "DATABASE_RO_URL"):
        assert key not in web, key
    assert "/data" not in web and "lutetia-state" not in web
    assert re.findall(r"^\s+- (\S+:\S+:ro)\s*(?:#.*)?$", web, re.M) == ["./callers:/callers:ro"]  # the only mount, read-only


def test_web_connects_as_readonly_role_and_runs_web_role():
    web = service_block("web")
    assert re.search(r"DATABASE_URL: postgresql://lutetia_ro:\$\{DATABASE_RO_PASSWORD:\?[^}]+\}@db:5432/lutetia", web)
    assert 'command: ["lutetia", "run", "--role", "web"]' in web
    assert "DASHBOARD_PWD: ${DASHBOARD_PWD:?" in web and "API_KEY: ${API_KEY:?" in web
    assert re.search(r"collector:\n\s+condition: service_started", web)  # ADR-4: web does not wait for collector health
    assert "service_healthy" not in web
    assert "restart: unless-stopped" in web


def test_collector_sets_ro_password_and_runs_collector_role():
    col = service_block("collector")
    assert "DATABASE_RO_PASSWORD: ${DATABASE_RO_PASSWORD:?" in col
    assert "lutetia migrate && exec lutetia run --role collector" in col
    assert "env_file: .env" in col
    assert "postgresql://lutetia:" in col  # write account stays with the collector
    assert "DASHBOARD_PWD" not in col


def test_published_ports_loopback_only_and_split():
    col, web = service_block("collector"), service_block("web")
    assert re.findall(r'- "([^"]+)"', col) == ["127.0.0.1:${PUSH_PUBLISH_PORT:-8080}:8080"]
    assert re.findall(r'- "([^"]+)"', web) == ["127.0.0.1:${DASHBOARD_PUBLISH_PORT:-8081}:8081"]
    for line in re.findall(r'^\s+- "(\S+:\d+)"$', TEXT, re.M):
        assert line.startswith("127.0.0.1:"), line


def test_healthchecks_present_without_curl():
    for name in ("collector", "web"):
        blk = service_block(name)
        assert "healthcheck:" in blk and "curl" not in blk
    assert "/health'" in service_block("collector") and "/login'" in service_block("web")


def test_web_session_secret_is_required():
    web = service_block("web")
    assert "SESSION_SECRET: ${SESSION_SECRET:?set SESSION_SECRET in .env}" in web
    assert "SESSION_SECRET:-" not in web


def test_web_gets_orange_huawei_account_keys_collector_does_not():
    web, col = service_block("web"), service_block("collector")
    for line in ("ORANGE_USER: ${ORANGE_USER:-orange}", "ORANGE_PWD: ${ORANGE_PWD:-}",
                 "HUAWEI_USER: ${HUAWEI_USER:-huawei}", "HUAWEI_PWD: ${HUAWEI_PWD:-}"):
        assert line in web, line
    for key in ("ORANGE_", "HUAWEI_"):
        assert key not in col, key


def test_web_gets_callers_file_and_rate_keys_collector_does_not():
    web, col = service_block("web"), service_block("collector")
    for line in ("CALLERS_FILE: ${CALLERS_FILE:-}", "LEGACY_RATE_PER_MIN: ${LEGACY_RATE_PER_MIN:-600}",
                 "SESSION_RATE_PER_MIN: ${SESSION_RATE_PER_MIN:-600}", "- ./callers:/callers:ro"):
        assert line in web, line
    for key in ("CALLERS_FILE", "RATE_PER_MIN", "/callers"):
        assert key not in col, key
