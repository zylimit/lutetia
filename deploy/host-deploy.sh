#!/usr/bin/env bash
# 云主机部署（幂等）：在主机 ~/lutetia 下运行 bash deploy/host-deploy.sh
set -euo pipefail

DOMAIN=iot.digifiber.net
CONF_SRC=deploy/nginx/${DOMAIN}.conf
CONF_DST=/etc/nginx/sites-available/${DOMAIN}
CONF_LINK=/etc/nginx/sites-enabled/${DOMAIN}
ENV_FILE=.env
CERT_DIR=/etc/letsencrypt/live/${DOMAIN}

SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"  # cd 之前先固定绝对路径：之后 sha256sum / exec 在任何调用方式下都找得到本脚本
cd "$(dirname "$SELF")/.."

echo "[1/8] 拉取最新代码（只快进）"
before=$(sha256sum "$SELF" | cut -d' ' -f1)
git pull --ff-only
# 本脚本自己被 pull 更新时，用新版本重跑一遍（环境变量防无限重入）
if [ -z "${LUTETIA_DEPLOY_REEXEC:-}" ] && [ "$before" != "$(sha256sum "$SELF" | cut -d' ' -f1)" ]; then
  echo "host-deploy.sh 已更新，用新版本重跑"
  export LUTETIA_DEPLOY_REEXEC=1
  exec bash "$SELF" "$@"
fi

echo "[2/8] 检查环境文件存在且必填键非空（不打印值）"
if [ ! -f "$ENV_FILE" ]; then
  echo "缺 ${ENV_FILE}：先从本机 scp 到主机 ~/lutetia/" >&2
  exit 1
fi
for key in DASHBOARD_PWD API_KEY PUSH_PATH DATABASE_RO_PASSWORD; do
  if ! grep -qE "^${key}=.+" "$ENV_FILE"; then
    echo "${ENV_FILE} 里 ${key} 缺失或为空" >&2
    exit 1
  fi
done
# 密码拼进 postgresql://… 连接串：含 / @ # ? % 会让串解析失败或连错账号，所以只许字母数字
if ! grep -qE '^DATABASE_RO_PASSWORD=[A-Za-z0-9]+$' "$ENV_FILE"; then
  echo "${ENV_FILE} 里 DATABASE_RO_PASSWORD 只能用字母数字（建议 openssl rand -hex 24 生成）" >&2
  exit 1
fi

echo "[3/8] 构建并启动容器，等 collector 与 web 都 healthy"
docker compose up -d --build

wait_healthy() {
  local svc=$1 limit=${HEALTH_WAIT_SEC:-180} cid status=none deadline
  deadline=$((SECONDS + limit))
  while [ "$SECONDS" -lt "$deadline" ]; do
    cid=$(docker compose ps -q "$svc")
    status=none
    if [ -n "$cid" ]; then
      status=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid" 2>/dev/null || echo none)
    fi
    if [ "$status" = healthy ]; then
      echo "${svc} healthy"
      return 0
    fi
    sleep 3
  done
  echo "${svc} 在 ${limit}s 内没有变 healthy（当前 ${status}）；用 docker compose logs ${svc} 查原因" >&2
  return 1
}

wait_healthy collector
wait_healthy web

install_site() {
  if sudo test -e "$CONF_DST" && sudo grep -q 'managed by Certbot' "$CONF_DST"; then
    echo "站点配置已由 certbot 接管，跳过覆盖；要更新 server block：sudo rm 该文件后重跑，脚本会重新把证书装回配置"
  else
    sudo install -m 644 "$CONF_SRC" "$CONF_DST"
    echo "已安装站点配置 ${CONF_DST}"
  fi
  sudo ln -sfn "$CONF_DST" "$CONF_LINK"
}

echo "[4/8] 安装 nginx 站点配置"
install_site

echo "[5/8] nginx -t 校验（失败则不 reload，既有站点不受影响）"
sudo nginx -t

echo "[6/8] reload nginx"
sudo systemctl reload nginx

ensure_cert() {
  if ! sudo test -d "$CERT_DIR"; then
    sudo certbot --nginx -d "$DOMAIN" --redirect -n --agree-tos
  elif sudo grep -q 'managed by Certbot' "$CONF_DST"; then
    echo "证书与配置都在，跳过"
  else
    echo "证书在、配置里没有 443（被重装过），把现有证书重新装进 server block"
    sudo certbot install --cert-name "$DOMAIN" --nginx --redirect -n
  fi
}

echo "[7/8] 证书"
ensure_cert

install_backup_timer() {
  local repo unit
  repo=$(pwd)
  if ! sudo test -f /etc/lutetia/backup.env; then
    echo "备份定时器未启用：缺 /etc/lutetia/backup.env（COS_BUCKET 等由你在主机上亲手写入）；写好后重跑本脚本即启用"
    return 0
  fi
  for unit in lutetia-backup.service lutetia-backup.timer; do
    sed "s|@REPO@|${repo}|g" "deploy/${unit}" | sudo tee "/etc/systemd/system/${unit}" >/dev/null
  done
  sudo systemctl daemon-reload
  sudo systemctl enable --now lutetia-backup.timer
  echo "备份定时器已启用，下次触发："
  systemctl list-timers lutetia-backup.timer --no-pager | head -3
}

echo "[8/8] 备份定时器（需要 /etc/lutetia/backup.env）"
install_backup_timer

echo "== 冒烟 =="
echo "-- 看板登录页首行"
curl -sI "https://${DOMAIN}/login" | head -1
echo "-- /health"
curl -s "https://${DOMAIN}/health"
echo
echo "-- 容器状态"
docker compose ps

sudo grep -q 'managed by Certbot' "$CONF_DST" || { echo "配置里没有 443，部署失败" >&2; exit 1; }
