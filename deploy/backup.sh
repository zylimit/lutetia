#!/usr/bin/env bash
# 生产库每日备份：pg_dump -> 本地 -> coscli 上传 COS（eu-frankfurt）-> backup_run 记一行。
# 在 fra 宿主机的仓库目录运行，由 lutetia-backup.timer 每天 02:30（Europe/Paris）触发；也可手动：
#   sudo deploy/backup.sh               # 完整流程
#   sudo deploy/backup.sh --local-only  # 不上传，只 dump 与记录（object_key 为空），没有 COS 凭据时验证用
#
# 凭据与桶：只来自环境变量，由 systemd EnvironmentFile=/etc/lutetia/backup.env 提供（COS_BUCKET 必填）。
# coscli 自己的配置（SecretId / SecretKey / endpoint 等）由用户在主机上自行配置好，本脚本不读、不写、不打印。
# 上传密钥只给写入权限、不给删除；保留期由 COS 桶的生命周期规则负责，本脚本永不删除远端对象。
# 失败也会往 backup_run 插一行（ok=false，error 只写阶段与退出码或信号），然后以非零码退出。
# 可选环境变量 COSCLI_CONFIG：coscli 配置文件路径（-c），不设则用 coscli 默认的 ~/.cos.yaml（root 跑就是 /root/.cos.yaml）。
set -euo pipefail
umask 077  # dump 含 GPS 位置，只给属主读写（DFX THR-6）

LOCAL_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --local-only) LOCAL_ONLY=1 ;;
    *) echo "未知参数：$arg（只支持 --local-only）" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."

BACKUP_DIR=${BACKUP_DIR:-/var/backups/lutetia}
KEEP_LOCAL=2
STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILENAME=lutetia-${STAMP}.dump
DUMP_PATH=${BACKUP_DIR}/${FILENAME}

# 周日（Europe/Paris）为 weekly
if [ "$(TZ=Europe/Paris date +%u)" = "7" ]; then KIND=weekly; else KIND=daily; fi

STAGE=init
OK=false
ERROR=
OBJECT_KEY=
BYTES=
SHA256=
ROW_COUNTS=
ROW_COUNTS_AFTER=

db_psql() { docker compose exec -T db psql -U lutetia -d lutetia "$@"; }

record_run() {
  # 值全部走 psql -v 变量，由 :'name' 做引号转义，不拼 SQL
  db_psql -v ON_ERROR_STOP=1 -q \
    -v "started=${STARTED_AT}" -v "ok=${OK}" -v "kind=${KIND}" -v "object_key=${OBJECT_KEY}" \
    -v "bytes=${BYTES}" -v "sha256=${SHA256}" -v "row_counts=${ROW_COUNTS}" -v "row_counts_after=${ROW_COUNTS_AFTER}" -v "err=${ERROR}" <<'SQL'
INSERT INTO backup_run (started_at, finished_at, ok, kind, object_key, bytes, sha256, row_counts, row_counts_after, error)
VALUES (:'started'::timestamptz, now(), :'ok'::boolean, :'kind', NULLIF(:'object_key', ''),
        NULLIF(:'bytes', '')::bigint, NULLIF(:'sha256', ''), NULLIF(:'row_counts', '')::jsonb,
        NULLIF(:'row_counts_after', '')::jsonb, NULLIF(:'err', ''));
SQL
}

on_exit() {
  local rc=$?
  trap - EXIT
  set +e
  if [ "$rc" -ne 0 ]; then
    OK=false
    [ -n "$ERROR" ] || ERROR="stage=${STAGE} exit=${rc}"
    rm -f "${DUMP_PATH}.partial"
  fi
  ERROR=$(printf '%s' "$ERROR" | tr '\n\r' '  ' | cut -c1-300)
  if ! record_run; then
    echo "backup_run 记录失败（stage=${STAGE}）" >&2
    [ "$rc" -ne 0 ] || rc=1
  fi
  if [ "$rc" -ne 0 ]; then echo "备份失败：${ERROR}" >&2; else echo "备份完成：${FILENAME} kind=${KIND} bytes=${BYTES}"; fi
  exit "$rc"
}
trap on_exit EXIT
# 信号（如 TimeoutStartSec 到点 systemd 发 SIGTERM）也走 on_exit：记 ok=false 与原因，清 .partial，不打印「备份完成」
trap 'ERROR="stage=${STAGE} signal=TERM"; exit 143' TERM
trap 'ERROR="stage=${STAGE} signal=INT"; exit 130' INT

STAGE=config
if [ "$LOCAL_ONLY" -eq 0 ]; then
  [ -n "${COS_BUCKET:-}" ] || { ERROR="stage=config COS_BUCKET 未设置"; exit 1; }
  command -v coscli >/dev/null 2>&1 || { ERROR="stage=config 找不到 coscli"; exit 1; }
  COSCLI=(coscli)
  if [ -n "${COSCLI_CONFIG:-}" ]; then
    [ -f "$COSCLI_CONFIG" ] || { ERROR="stage=config coscli 配置文件不存在"; exit 1; }
    COSCLI=(coscli -c "$COSCLI_CONFIG")
  fi
fi

# dump 前后各数一次：采集器 dump 期间仍在写入，表只增不删（upsert），
# 所以恢复出的每表行数应满足 row_counts <= 恢复值 <= row_counts_after
count_rows() {
  db_psql -tAc "SELECT jsonb_build_object(
  'device', (SELECT count(*) FROM device),
  'gps_position', (SELECT count(*) FROM gps_position),
  'sensor_telemetry', (SELECT count(*) FROM sensor_telemetry),
  'sensor_attribute', (SELECT count(*) FROM sensor_attribute),
  'api_call', (SELECT count(*) FROM api_call),
  'poi', (SELECT count(*) FROM poi),
  'poi_cable_segment', (SELECT count(*) FROM poi_cable_segment))::text"
}

STAGE=row-counts
ROW_COUNTS=$(count_rows)

STAGE=dump
mkdir -p -m 700 "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
docker compose exec -T db pg_dump -U lutetia -Fc lutetia > "${DUMP_PATH}.partial"
STAGE=row-counts-after
ROW_COUNTS_AFTER=$(count_rows)
STAGE=dump
mv "${DUMP_PATH}.partial" "$DUMP_PATH"
if command -v sha256sum >/dev/null 2>&1; then
  SHA256=$(sha256sum "$DUMP_PATH" | cut -d' ' -f1)
else
  SHA256=$(shasum -a 256 "$DUMP_PATH" | cut -d' ' -f1)
fi
BYTES=$(wc -c < "$DUMP_PATH" | tr -d ' ')
[ "$BYTES" -gt 0 ] || { ERROR="stage=dump 备份文件为空"; exit 1; }

STAGE=retention
# 只清本地，留最近 KEEP_LOCAL 份；放在上传之前，上传反复失败也不会撑爆磁盘；远端对象不动
rm -f -- "$BACKUP_DIR"/lutetia-*.dump.partial  # 被 SIGKILL 等留下的残片
old=$(ls -1t "$BACKUP_DIR"/lutetia-*.dump | tail -n +"$((KEEP_LOCAL + 1))" || true)
if [ -n "$old" ]; then
  while IFS= read -r f; do rm -f -- "$f"; done <<< "$old"
fi

if [ "$LOCAL_ONLY" -eq 0 ]; then
  # 周日先传 daily/ 再传 weekly/，同一个文件、同一个 sha256；任一失败都算整次失败
  targets=(daily)
  [ "$KIND" = "weekly" ] && targets+=(weekly)
  for t in "${targets[@]}"; do
    STAGE=upload-${t}
    "${COSCLI[@]}" cp "$DUMP_PATH" "cos://${COS_BUCKET}/${t}/${FILENAME}"
  done
  OBJECT_KEY=${KIND}/${FILENAME}
fi

STAGE=done
OK=true
