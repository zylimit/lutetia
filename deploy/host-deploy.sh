#!/usr/bin/env bash
# 云主机部署（幂等）：在主机 ~/lutetia 下运行 bash deploy/host-deploy.sh
set -euo pipefail

DOMAIN=iot.digifiber.net
CONF_SRC=deploy/nginx/${DOMAIN}.conf
CONF_DST=/etc/nginx/sites-available/${DOMAIN}
CONF_LINK=/etc/nginx/sites-enabled/${DOMAIN}
ENV_FILE=.env
CERT_DIR=/etc/letsencrypt/live/${DOMAIN}

cd "$(dirname "$0")/.."

echo "[1/7] 拉取最新代码（只快进）"
git pull --ff-only

echo "[2/7] 检查环境文件存在且必填键非空（不打印值）"
if [ ! -f "$ENV_FILE" ]; then
  echo "缺 ${ENV_FILE}：先从本机 scp 到主机 ~/lutetia/" >&2
  exit 1
fi
for key in DASHBOARD_PWD API_KEY PUSH_PATH; do
  if ! grep -qE "^${key}=.+" "$ENV_FILE"; then
    echo "${ENV_FILE} 里 ${key} 缺失或为空" >&2
    exit 1
  fi
done

echo "[3/7] 构建并启动容器"
docker compose up -d --build

install_site() {
  if sudo test -e "$CONF_DST" && sudo grep -q 'managed by Certbot' "$CONF_DST"; then
    echo "站点配置已由 certbot 接管，跳过覆盖；要更新 server block：sudo rm 该文件后重跑，脚本会重新把证书装回配置"
  else
    sudo install -m 644 "$CONF_SRC" "$CONF_DST"
    echo "已安装站点配置 ${CONF_DST}"
  fi
  sudo ln -sfn "$CONF_DST" "$CONF_LINK"
}

echo "[4/7] 安装 nginx 站点配置"
install_site

echo "[5/7] nginx -t 校验（失败则不 reload，既有站点不受影响）"
sudo nginx -t

echo "[6/7] reload nginx"
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

echo "[7/7] 证书"
ensure_cert

echo "== 冒烟 =="
echo "-- 看板登录页首行"
curl -sI "https://${DOMAIN}/login" | head -1
echo "-- /health"
curl -s "https://${DOMAIN}/health"
echo
echo "-- 容器状态"
docker compose ps

sudo grep -q 'managed by Certbot' "$CONF_DST" || { echo "配置里没有 443，部署失败" >&2; exit 1; }
