#!/usr/bin/env bash
# 恢复演练：把一份备份 dump 恢复进一次性 postgres 容器，核对七张表行数落在 backup_run 记的区间内。
# 在 fra 宿主机的仓库目录运行（需要 docker compose 的 db 服务在跑，只用来查 backup_run）：
#   deploy/restore-drill.sh --file /path/to/lutetia-<UTC 时间戳>.dump   # 用户从 COS 控制台下载好的文件
#   COS_BUCKET=… COSCLI_READ_CONFIG=/path/read.yaml deploy/restore-drill.sh --from-cos   # 自动下载 daily/ 最新一份
#   加 --check-delete-denied：另测「上传密钥删不掉对象」（见下）
#
# 为什么 --from-cos 要单独的读配置：备份上传密钥按设计只有写入权限（DFX THR-6），读不了；
# 读取要用另一把只读密钥对应的 coscli 配置（环境变量 COSCLI_READ_CONFIG，文件由用户在主机上配好，本脚本不读内容、不打印）。
#
# 判定：每表 row_counts(dump 前) <= 恢复值 <= row_counts_after(dump 后)，含两端；采集在 dump 期间仍在写、表只增不删。
#   backup_run 行按文件 sha256 匹配（最近一条 ok=true）：本地备份（object_key 为空）与周日 weekly 行都适用，且证明文件与备份时字节一致；对不上即失败。
# 隔离：临时容器 postgres:16-alpine，随机名、独立 docker 网络、不挂任何卷、密码每次随机且不打印；
#   退出（含失败与信号）一律删容器与网络。永不碰生产库与生产卷（生产库只被只读地查一次 backup_run）。
#
# --check-delete-denied（有意尝试删除！）：不能看 coscli rm 的退出码判断——coscli 会丢弃删除调用的返回值、
#   先 HEAD 对象（HEAD 被拒也非零）、不加 -f 还会等确认，退出码分不清「删除被拒」与「HEAD 被拒」与「静默失败」。
#   所以三步，以对象是否还在为准（必须有只读密钥配置 COSCLI_READ_CONFIG，--file 模式也要）：
#   1. 用读配置 `coscli ls` 确认对象存在（不存在或查询出错 → FAIL，不尝试删除）；
#   2. 用写配置（COSCLI_CONFIG，同 backup.sh，不设则 coscli 默认配置）执行 `coscli rm -f cos://$COS_BUCKET/<对象>`，
#      stdin 接 /dev/null，退出码只记日志、不参与判定；
#   3. 再用读配置 ls：对象仍在 = PASS；对象没了 = 大声 FAIL（上传密钥能删备份，对象已没，立刻修密钥策略并重新备份）；
#      复查本身出错 = FAIL「无法确认」。不确定一律不 PASS。
#   对象取匹配到的 backup_run 行的 object_key；为空（本地备份）直接 FAIL，不尝试删除。需要 COS_BUCKET。
#
# 退出码：0 = 七表全 OK（且 delete-denied 通过，若要求）；1 = 演练失败；2 = 用法错误。
set -euo pipefail
umask 077  # 下载的 dump 含 GPS 位置，只给属主读写（DFX THR-6）

TABLES=(device gps_position sensor_telemetry sensor_attribute api_call poi poi_cable_segment)
IMAGE=postgres:16-alpine

FILE=
FROM_COS=0
CHECK_DELETE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --file) [ $# -ge 2 ] || { echo "--file 需要路径" >&2; exit 2; }; FILE=$2; shift 2 ;;
    --from-cos) FROM_COS=1; shift ;;
    --check-delete-denied) CHECK_DELETE=1; shift ;;
    *) echo "未知参数：$1（支持 --file <path> | --from-cos，可加 --check-delete-denied）" >&2; exit 2 ;;
  esac
done
if [ -z "$FILE" ] && [ "$FROM_COS" -eq 0 ]; then
  echo "必须给输入：--file <dump 路径> 或 --from-cos" >&2; exit 2
fi
if [ -n "$FILE" ] && [ "$FROM_COS" -eq 1 ]; then
  echo "--file 与 --from-cos 只能二选一" >&2; exit 2
fi

cd "$(dirname "$0")/.."

CONTAINER=
NETWORK=
WORKDIR=
cleanup() {
  local rc=$?
  trap - EXIT
  set +e
  [ -z "$CONTAINER" ] || docker rm -f "$CONTAINER" >/dev/null 2>&1
  [ -z "$NETWORK" ] || docker network rm "$NETWORK" >/dev/null 2>&1
  [ -z "$WORKDIR" ] || rm -rf -- "$WORKDIR"
  exit "$rc"
}
trap cleanup EXIT
trap 'echo "演练被信号 TERM 中断" >&2; exit 143' TERM
trap 'echo "演练被信号 INT 中断" >&2; exit 130' INT

die() { echo "演练失败：$*" >&2; exit 1; }

db_psql() { docker compose exec -T db psql -U lutetia -d lutetia "$@"; }

COSREAD=()
if [ "$FROM_COS" -eq 1 ] || [ "$CHECK_DELETE" -eq 1 ]; then
  [ -n "${COS_BUCKET:-}" ] || die "COS_BUCKET 未设置"
  [ -n "${COSCLI_READ_CONFIG:-}" ] || die "COSCLI_READ_CONFIG 未设置（--from-cos / --check-delete-denied 需要只读密钥的 coscli 配置；上传密钥读不了，见脚本头注释）"
  [ -f "$COSCLI_READ_CONFIG" ] || die "COSCLI_READ_CONFIG 指向的配置文件不存在"
  command -v coscli >/dev/null 2>&1 || die "找不到 coscli"
  COSREAD=(coscli -c "$COSCLI_READ_CONFIG")
fi
if [ "$CHECK_DELETE" -eq 1 ]; then
  COSWRITE=(coscli)
  if [ -n "${COSCLI_CONFIG:-}" ]; then
    [ -f "$COSCLI_CONFIG" ] || die "COSCLI_CONFIG 指向的配置文件不存在"
    COSWRITE=(coscli -c "$COSCLI_CONFIG")
  fi
fi

# 1. 取得文件；--from-cos 先列 daily/ 取时间戳最大的一份（文件名里是 UTC 时间戳，字典序即时间序），下载后再核对
#    计时从下载（或恢复）开始
START=$SECONDS
if [ "$FROM_COS" -eq 1 ]; then
  LISTING=$("${COSREAD[@]}" ls "cos://${COS_BUCKET}/daily/") || die "列 COS daily/ 失败"
  FILENAME=$(printf '%s\n' "$LISTING" | grep -oE 'lutetia-[0-9]{8}T[0-9]{6}Z\.dump' | sort -u | tail -n 1 || true)
  [ -n "$FILENAME" ] || die "COS daily/ 下没有 lutetia-*.dump"
  WORKDIR=$(mktemp -d)
  FILE=${WORKDIR}/${FILENAME}
  "${COSREAD[@]}" cp "cos://${COS_BUCKET}/daily/${FILENAME}" "$FILE" || die "下载失败"
else
  [ -f "$FILE" ] || die "文件不存在：$FILE"
  FILENAME=$(basename "$FILE")
fi
[ -s "$FILE" ] || die "备份文件为空：$FILE"

# 2. 按文件 sha256 找 backup_run 行（值走 psql -v，:'sha' 转义，不拼 SQL）；取最近一条成功记录。
#    不按文件名：本地备份（object_key 为空）与周日 weekly 行都适用，且证明这份文件与备份时字节一致
if command -v sha256sum >/dev/null 2>&1; then
  SHA=$(sha256sum "$FILE" | cut -d' ' -f1)
else
  SHA=$(shasum -a 256 "$FILE" | cut -d' ' -f1)
fi
[ "${#SHA}" -eq 64 ] || die "计算 sha256 失败：$FILE"
MATCH=$(db_psql -v ON_ERROR_STOP=1 -tAq -F '|' -v "sha=${SHA}" <<'SQL'
SELECT id, coalesce(object_key, '') FROM backup_run
 WHERE ok AND sha256 = :'sha'
 ORDER BY id DESC LIMIT 1;
SQL
) || die "查询 backup_run 失败"
[ -n "$MATCH" ] || die "这份文件不是任何一次成功备份的原样副本（sha256 对不上）：${FILENAME} sha256=${SHA}"
RUN_ID=${MATCH%%|*}
OBJECT_KEY=${MATCH#*|}
BOUNDS=$(db_psql -v ON_ERROR_STOP=1 -tAq -F '|' -v "rid=${RUN_ID}" <<'SQL'
SELECT t.k, r.row_counts ->> t.k, r.row_counts_after ->> t.k
  FROM backup_run r,
       unnest(ARRAY['device','gps_position','sensor_telemetry','sensor_attribute','api_call','poi','poi_cable_segment']) AS t(k)
 WHERE r.id = :'rid'::bigint
 ORDER BY array_position(ARRAY['device','gps_position','sensor_telemetry','sensor_attribute','api_call','poi','poi_cable_segment'], t.k);
SQL
) || die "读取行数区间失败"
echo "备份记录：backup_run#${RUN_ID} object_key=${OBJECT_KEY:-（无，本地备份）} sha256=${SHA}"

# 4. 一次性容器：独立网络、无卷；密码只经环境变量传入、不打印
SUFFIX=$(od -An -N6 -tx1 /dev/urandom | tr -d ' \n')
CONTAINER=lutetia-drill-${SUFFIX}
NETWORK_NAME=lutetia-drill-net-${SUFFIX}
POSTGRES_PASSWORD=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
export POSTGRES_PASSWORD
docker network create "$NETWORK_NAME" >/dev/null || die "建临时网络失败"
NETWORK=$NETWORK_NAME
docker run -d --name "$CONTAINER" --network "$NETWORK" -e POSTGRES_PASSWORD "$IMAGE" >/dev/null \
  || die "起临时容器失败"
unset POSTGRES_PASSWORD

# 走 TCP（127.0.0.1）探测：初始化阶段的临时服务只听 unix socket，TCP 通了才是正式服务
ready=0
for _ in $(seq 1 90); do
  if docker exec "$CONTAINER" pg_isready -h 127.0.0.1 -U postgres >/dev/null 2>&1; then ready=1; break; fi
  sleep 1
done
[ "$ready" -eq 1 ] || die "临时容器 90 秒内没就绪"

docker exec -i "$CONTAINER" pg_restore --no-owner --no-privileges -U postgres -d postgres < "$FILE" || die "pg_restore 失败"

# 5. 数行
RESTORED=$(docker exec "$CONTAINER" psql -U postgres -d postgres -tA -F '|' -c "
SELECT 'device', count(*) FROM device UNION ALL
SELECT 'gps_position', count(*) FROM gps_position UNION ALL
SELECT 'sensor_telemetry', count(*) FROM sensor_telemetry UNION ALL
SELECT 'sensor_attribute', count(*) FROM sensor_attribute UNION ALL
SELECT 'api_call', count(*) FROM api_call UNION ALL
SELECT 'poi', count(*) FROM poi UNION ALL
SELECT 'poi_cable_segment', count(*) FROM poi_cable_segment") || die "恢复库数行失败（恢复后七张表是否有缺失？）"
ELAPSED=$((SECONDS - START))

is_int() { case "$1" in ''|*[!0-9]*) return 1 ;; *) return 0 ;; esac; }
FAILS=0
for t in "${TABLES[@]}"; do
  before=$(printf '%s\n' "$BOUNDS" | awk -F'|' -v t="$t" '$1 == t { print $2 }')
  after=$(printf '%s\n' "$BOUNDS" | awk -F'|' -v t="$t" '$1 == t { print $3 }')
  got=$(printf '%s\n' "$RESTORED" | awk -F'|' -v t="$t" '$1 == t { print $2 }')
  if [ -z "$before" ] || [ -z "$after" ]; then
    echo "${t} backup_run#${RUN_ID} 里没有该表的行数区间  FAIL"
    FAILS=$((FAILS + 1)); continue
  fi
  if [ -z "$got" ]; then
    echo "${t} 恢复后不存在  FAIL"
    FAILS=$((FAILS + 1)); continue
  fi
  if is_int "$before" && is_int "$after" && is_int "$got" && [ "$before" -le "$got" ] && [ "$got" -le "$after" ]; then
    verdict=OK
  else
    verdict=FAIL; FAILS=$((FAILS + 1))
  fi
  echo "${t} ${before:-?} ≤ ${got:-?} ≤ ${after:-?}  ${verdict}"
done
echo "总耗时：${ELAPSED} 秒"

# 6. 可选：上传密钥删除必须被拒；以读配置复查对象是否还在为准，不信 rm 的退出码
# 返回 0 = 对象在，1 = 不在，2 = 查询出错（无法确认）
cos_has_object() {
  local out
  out=$("${COSREAD[@]}" ls "cos://${COS_BUCKET}/${OBJECT_KEY}") || return 2
  printf '%s\n' "$out" | grep -qF -- "${OBJECT_KEY##*/}"
}
DELETE_RC=0
if [ "$CHECK_DELETE" -eq 1 ] && [ -z "$OBJECT_KEY" ]; then
  echo "FAIL：本地备份没有 COS 对象，删除测试需要上传过的备份（backup_run#${RUN_ID} 的 object_key 为空；未尝试删除）" >&2
  DELETE_RC=1
elif [ "$CHECK_DELETE" -eq 1 ]; then
  pre=0; cos_has_object || pre=$?
  if [ "$pre" -ne 0 ]; then
    echo "FAIL：删除测试前置不满足——读配置$([ "$pre" -eq 2 ] && echo ' ls 出错，无法确认对象存在' || echo '看不到对象')：${OBJECT_KEY}（未尝试删除）" >&2
    DELETE_RC=1
  else
    echo "注意：--check-delete-denied 会真的尝试删除 cos://${COS_BUCKET}/${OBJECT_KEY}"
    rm_rc=0
    "${COSWRITE[@]}" rm -f "cos://${COS_BUCKET}/${OBJECT_KEY}" </dev/null >/dev/null 2>&1 || rm_rc=$?
    echo "coscli rm 退出码 ${rm_rc}（仅记录，不参与判定）"
    post=0; cos_has_object || post=$?
    case "$post" in
      0) echo "delete-denied PASS：删除尝试后对象仍在，上传密钥删不掉备份" ;;
      1) echo "FAIL：upload key can delete — fix the key policy now（对象 ${OBJECT_KEY} 已被删除，修好密钥策略后立即重新备份）" >&2
         DELETE_RC=1 ;;
      *) echo "FAIL：删除后复查 ls 出错，cannot confirm 对象是否还在（不按 PASS 处理；请人工查 COS 控制台 ${OBJECT_KEY}）" >&2
         DELETE_RC=1 ;;
    esac
  fi
fi

if [ "$FAILS" -gt 0 ]; then die "${FAILS} 张表行数越界"; fi
if [ "$DELETE_RC" -ne 0 ]; then exit 1; fi
echo "恢复演练通过：${FILENAME}"
