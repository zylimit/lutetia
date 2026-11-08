# Lutetia

巴黎项目 IoT 数据采集服务：把 GPS51（途强物联 GPS）和 Dingtek Cloud（DC414 井盖传感器）的数据持续落到自己的 PostgreSQL。需求与设计约束见 `Product-Spec.md`，两家接口的调研结论和真实样例见 `docs/vendor/`。

## 本地开发

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env            # 填 GPS51_* / DINGTEK_* 凭据
docker run -d --name lutetia-pg -e POSTGRES_USER=lutetia -e POSTGRES_PASSWORD=lutetia -e POSTGRES_DB=lutetia -p 127.0.0.1:15433:5432 postgres:16-alpine
lutetia migrate
pytest
```

## 命令

| 命令 | 作用 |
|---|---|
| `lutetia migrate` | 建表（幂等） |
| `lutetia backfill dingtek --from 2026-08-21` | REST 全量回补，可重复执行，第二次新增为 0 |
| `lutetia run [--role collector\|web\|all]` | 常驻（默认 `all`，本机开发一个进程全起；部署为 collector + web 两个容器）：GPS51 推送接收端 + 静默 15 分钟后轮询；Dingtek WebSocket 订阅 + 每日回补 |
| `lutetia status` | 每台设备最后入库时间；在线设备超过 3 小时无数据则退出码 1 |
| `lutetia import poi FILE [--dry-run]` | 导入 POI 台账 xlsx，打印汇总数字；`--dry-run` 只算不写；读出 0 个工单拒绝导入 |
| `lutetia gps51 sync-devices` / `poll-once` | 手工同步设备、单次轮询 |
| `lutetia gps51 tracks --device ID --begin '2026-10-06 00:00:00' --end '2026-10-06 23:59:59'` | 单次历史轨迹，每设备每天限 5 次，只能手工 |

## 看板与登录

看板由 web 容器（`lutetia run --role web`，本机开发的 `all` 模式下是同进程的第二个 HTTP 监听）提供，只读（服务端渲染 + 每 60 秒局部刷新，没有任何写入口）。v0.2.0 起看板有四块：首页顶部异常总览（失联 / 低电压 / 报警 / 推送通道 / GPS51 配额 / Dingtek 登录次数，无异常显示「全部正常」）、设备详情页（点任一设备名：井盖 7 / 30 天电压温度信号曲线 + 最近 50 条 + 属性表，GPS 最后位置小地图 + 位置表 + 里程）、位置地图页（`/dashboard/map`，12 台井盖固定点 + GPS 最后位置，`?tracks=1` 带近 7 天轨迹（按 5 分钟一格抽稀，每格留最新一点），底图测试阶段直拉 Google 瓦片、标「不商用」，商用前换回 OSM 或 Google 官方 API）、手机宽度适配。图表与地图库（Chart.js 4.6.1、Leaflet 1.9.4）随包自托管在 `/static/`，不走 CDN；页面带 CSP 等安全头。本机打开 `http://127.0.0.1:8081/`，未登录会跳到登录页；账号 `DASHBOARD_USER`（默认 `admin`），密码 `DASHBOARD_PWD`，会话 cookie 12 小时有效，同一 IP 连续输错 5 次锁 5 分钟（`DASHBOARD_LOGIN_LOCKOUT=off` 可关）。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DASHBOARD_LISTEN_HOST` | `127.0.0.1` | 绑 `0.0.0.0` 必须同时设 `DASHBOARD_PWD` 与 `API_KEY`，否则启动报错退出 |
| `DASHBOARD_LISTEN_PORT` | `8081` | 监听端口 |
| `DASHBOARD_USER` | `admin` | 登录账号 |
| `DASHBOARD_PWD` | 空 | 登录密码，只从环境变量读；空则任何人都登不进 |
| `DASHBOARD_TRUST_PROXY` | `false` | 只在前面恰好一层受信反向代理（nginx）时设 `true`（仅信任回环/私网来源，取 X-Forwarded-For 最后一个值，即该代理追加的那个）；**直接绑公网时不要开**，否则伪造该头可绕过登录锁定 |
| `DASHBOARD_LOW_VOLT` | `3.4` | 首页异常总览的低电压阈值（V）：低于它标黄，再低 0.2 V 标红 |
| `DASHBOARD_LOGIN_LOCKOUT` | 开 | 设 `off` 关闭登录锁定（同 IP 错 5 次锁 5 分钟、全局 5 分钟 50 次锁 60 秒），仅测试阶段用；失败照常记日志 |
| `API_KEY` | 空 | 查询 API 的 Bearer key；空则所有 API 请求都返回 401 |
| `SESSION_SECRET` | 空 | cookie 签名密钥；空则每次启动随机生成，重启后要重新登录 |
| `DATABASE_RO_PASSWORD` | 空 | 只读库角色 `lutetia_ro` 的登录密码。collector 启动迁移时设到库里，web 容器用它连库（compose 里拼成 `postgresql://lutetia_ro:…@db:5432/lutetia`，所以没有 `DATABASE_RO_URL`）；`docker compose` 下必填，空则起不来；**只许字母数字**（密码直接拼进连接串，含 `/ @ # ? %` 会解析失败或连错账号；`host-deploy.sh` 第 2 步会校验），生成用 `openssl rand -hex 24`。轮换：改 `.env` 后重跑 `bash deploy/host-deploy.sh`。收回登录要手工执行 `ALTER ROLE lutetia_ro NOLOGIN PASSWORD NULL`（删掉变量不会收回） |

本机可以把 `DASHBOARD_PWD` 填成简单密码，**上云主机前必须换成强密码、`API_KEY` 换成随机长串**。`docker compose` 下 `DASHBOARD_PWD`、`API_KEY`、`DATABASE_RO_PASSWORD` 缺一不能启动；看板端口只发布到宿主机 `127.0.0.1:8081`，云主机经 HTTPS 域名访问（Phase 3）。

## 查询 API

只读 JSON，四个 GET 接口，没有任何写入接口。每个请求都要带 `Authorization: Bearer <API_KEY>`；缺头、key 错或服务端没配 `API_KEY` 一律返回 `401`，并带 `WWW-Authenticate: Bearer`。`since` / `until` 的时区偏移请用 `Z` 或把 `+` 编码为 `%2B`。

| 接口 | 参数 | 返回 |
|------|------|------|
| `GET /api/v1/devices` | 无 | `{"devices": [{source, device_id, name, device_type, expected_online, last_ts}]}` |
| `GET /api/v1/positions` | `device_id`（必填）、`since`、`until`、`limit` | `{"device_id", "count", "positions": [...]}`，每条含 `speed_kmh` 与 `speed_raw`，按 `update_time` 倒序 |
| `GET /api/v1/telemetry` | `device_id`（必填）、`key`、`since`、`until`、`limit` | `{"device_id", "count", "telemetry": [...]}`，每条含 `value_si`，按 `ts` 倒序 |
| `GET /api/v1/status` | 无 | `{"started_at", "receiver": {...} 或 null, "api_calls_24h": [...]}` |

- `since` / `until`：ISO 8601（`2026-11-01T00:00:00Z` 或 `+00:00`）或毫秒整数；解析失败返回 `400`。
- `limit`：默认 1000，范围 1 ～ 10000，越界返回 `400`；缺 `device_id` 返回 `400`。
- 时间字段统一输出 ISO 8601 UTC，带 `Z`。

```bash
curl -H "Authorization: Bearer $API_KEY" http://127.0.0.1:8081/api/v1/devices
curl -H "Authorization: Bearer $API_KEY" \
  "http://127.0.0.1:8081/api/v1/positions?device_id=4072400634&limit=10"
curl -H "Authorization: Bearer $API_KEY" \
  "http://127.0.0.1:8081/api/v1/telemetry?device_id=<uuid>&key=volt&since=2026-11-01T00:00:00Z"
```

## 部署（固定公网 IP 的云主机，nginx + certbot HTTPS）

主机上已有 nginx 与 certbot；本项目并入一个 `iot.digifiber.net` 的 server block，容器端口只绑 127.0.0.1，公网只有 nginx 的 443。

1. 把主机公网 IP（当前生产：法兰克福 43.165.4.9；主机必须在欧盟境内，见 Product-Spec 非功能表「合规」）加进 GPS51 后台「白名单」，openapi 才放行。
2. 首次：在主机克隆仓库到 `~/lutetia`，并在本机把环境文件 scp 到 `hub:~/lutetia/` 下（文件名见 `.env.example` 同目录）。必须有非空的 DASHBOARD_PWD、API_KEY、PUSH_PATH、DATABASE_RO_PASSWORD；PUSH_PATH 建议设成 `/gps51/push/<随机 20 位>`；主机 8081 被占，加一行 `DASHBOARD_PUBLISH_PORT=18081`（nginx 配置指向它）。
3. 在主机 `~/lutetia` 下运行 `bash deploy/host-deploy.sh`：git pull → 查必填键 → `docker compose up -d --build` → 等 collector 与 web 都 healthy → 装 nginx 配置 → `nginx -t` → reload → 无证书才 `certbot --nginx` → 打印冒烟结果。可重复运行。
   三个服务、同一镜像：`db`；`collector`（`lutetia migrate && lutetia run --role collector`：推送接收端与 `/health`、GPS51 / Dingtek 采集、心跳，发布 `127.0.0.1:8080`，持有写库账号与厂家账号）；`web`（`lutetia run --role web`：只读看板与查询 API，不整包注入环境文件，只拿看板用到的键，用只读角色 `lutetia_ro` 连库，发布 `127.0.0.1:8081`，只等 collector 容器启动、不等它健康）。web 停了推送照收、心跳照写；collector 停了看板照开、心跳显示过期。首次上线时 collector 还在迁移、只读角色还没密码，web 连库失败会以非零码退出，由 `restart: unless-stopped` 重试，collector 迁移完即自愈。`lutetia run --role collector|web|all` 默认 `all`（本机开发一个进程全起）。nginx 按路径分流：`/gps51/push` 与 `/health` 到 collector，其余到 web。
4. GPS51 后台「转发平台列表」新建 `Http Json` 转发，地址填 `https://iot.digifiber.net/gps51/push/<随机段>`；看板在 `https://iot.digifiber.net/dashboard/`。
   **首次部署本版本（Task 7.3）**：fra 上现存的部署脚本还是旧版，`git pull` 之后不会自动用新版重跑，所以先手动 `git pull --ff-only`，再 `bash deploy/host-deploy.sh`（或直接连跑两遍）。
   **回滚预案**（手动步骤，不要重跑 `host-deploy.sh`：`git checkout <tag>` 之后是分离 HEAD，脚本里的 `git pull --ff-only` 会失败）：① `git checkout <tag>`；② 跨 Task 7.3 回滚（回到单容器布局）时先 `docker compose rm -sf web`，否则旧 collector 会因 8081 端口被 web 占着而起不来；③ `docker compose up -d --build`；④ 查 `docker compose ps` 与 `/health`；⑤ 回到主线时先 `git checkout main`，再跑 `bash deploy/host-deploy.sh`。
5. `docker compose exec collector lutetia backfill dingtek --from 2026-08-21` 做首次回补。
6. 导入 POI 台账：先 `mkdir -p ~/lutetia/data/poi`（不先建的话 Docker 会自建成 root 属主），把 xlsx 放到主机 `~/lutetia/data/poi/`（只放在法兰克福主机，不经 GitHub、不出欧洲；compose 把它只读挂成容器内 `/ledger`），先 `docker compose exec collector lutetia import poi "/ledger/<文件>" --dry-run` 看汇总数字，对了再去掉 `--dry-run` 正式导入。
7. 用 `GET /health` 和 `lutetia status` 做监控。
   `/health` 返回字段：
   - `received`：收到并入队的推送数
   - `stored`：已写库的新行数
   - `rejected`：请求体为空或不是合法 JSON、被 400 拒绝的次数
   - `unrecognised`：合法 JSON 但认不出格式、未入库的推送数
   - `failed`：非数据库类异常、被丢弃的推送数
   - `queued`：队列里尚未写库的条数
   - `alarms`：报警转发（带 alarmtype）的条数，只计数不入库
   - `silent_sec`：距最近一条能认出的位置消息的秒数，轮询兜底看它
   - `message_silent_sec`：距最近一条合法 JSON 的秒数

## 备份

生产库是两家厂家数据的唯一存档，每天自动 `pg_dump` 一份传到腾讯云 COS（eu-frankfurt，数据不出欧洲）。

- 何时跑：`lutetia-backup.timer` 每天 02:30（Europe/Paris）触发 `deploy/backup.sh`；周日那份同时传到 `daily/` 与 `weekly/`（同一文件、同 sha256），其余日子只传 `daily/`。本地 `/var/backups/lutetia`（可用 `BACKUP_DIR` 改）只留最近 2 份。
- 记录：每次运行（成功或失败）在 `backup_run` 表插一行，含大小、sha256、dump 前后各表行数（表只增不删，恢复演练时每表应满足 前 ≤ 恢复值 ≤ 后）；被 systemd 超时（`TimeoutStartSec=3h`）或手动 kill 的运行记 `signal=TERM` / `signal=INT`；失败写 `ok=false` 与阶段原因，不写凭据，脚本随后以非零码退出。
- 启用：在主机亲手写好 `/etc/lutetia/backup.env`（至少 `COS_BUCKET=<桶名>`），并自行配置好 `coscli`：服务以 root 跑，所以用 `sudo coscli config init`（配置落在 `/root/.cos.yaml`），或把配置文件放别处并在 `backup.env` 里设 `COSCLI_CONFIG=<路径>`（脚本改调 `coscli -c`，文件不存在则 `stage=config` 失败）；`deploy/host-deploy.sh` 第 8 步检测到该文件才安装并启用 timer，没有就打印提示、不启用。凭据只放这个文件，不进仓库、不进日志。
- 手动 / 无凭据验证：`sudo deploy/backup.sh --local-only` 只 dump 与记录（`object_key` 为空），不上传。
- 周日恰逢主机宕机错过时，周一补跑按 daily 记，那一周没有 weekly——已接受。
- 桶清单（用户在腾讯云控制台自行核对）：私有桶、地域 eu-frankfurt；开默认服务端加密；开版本控制（只写密钥仍能覆盖同名对象，版本控制留住旧的）；配生命周期规则落实保留期（14 份 daily + 8 份 weekly）；密钥只给该桶的只写权限。
- 保留期由 COS 桶的生命周期规则负责（脚本永不删除远端对象）；上传密钥必须是只写、不带删除权限的子账号密钥，泄漏也删不掉备份。

## 数据表

`device`（两源混放，`source` 区分）、`gps_position`（宽表，去重键 deviceid+updatetime）、`sensor_telemetry`（窄表，去重键 uuid+key+ts）、`sensor_attribute`、`api_call`（调用计数）。原始值不换算，单位换算在 `gps_position_v` / `sensor_telemetry_v` 视图里。
