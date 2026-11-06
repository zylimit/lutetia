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
| `lutetia run` | 常驻：GPS51 推送接收端 + 静默 15 分钟后轮询；Dingtek WebSocket 订阅 + 每日回补 |
| `lutetia status` | 每台设备最后入库时间；在线设备超过 3 小时无数据则退出码 1 |
| `lutetia gps51 sync-devices` / `poll-once` | 手工同步设备、单次轮询 |
| `lutetia gps51 tracks --device ID --begin '2026-10-06 00:00:00' --end '2026-10-06 23:59:59'` | 单次历史轨迹，每设备每天限 5 次，只能手工 |

## 看板与登录

常驻服务里的第二个 HTTP 监听提供只读看板（服务端渲染，60 秒自动刷新，没有任何写入口）。本机打开 `http://127.0.0.1:8081/`，未登录会跳到登录页；账号 `DASHBOARD_USER`（默认 `admin`），密码 `DASHBOARD_PWD`，会话 cookie 12 小时有效，同一 IP 连续输错 5 次锁 5 分钟。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DASHBOARD_LISTEN_HOST` | `127.0.0.1` | 绑 `0.0.0.0` 必须同时设 `DASHBOARD_PWD` 与 `API_KEY`，否则启动报错退出 |
| `DASHBOARD_LISTEN_PORT` | `8081` | 监听端口 |
| `DASHBOARD_USER` | `admin` | 登录账号 |
| `DASHBOARD_PWD` | 空 | 登录密码，只从环境变量读；空则任何人都登不进 |
| `DASHBOARD_TRUST_PROXY` | `false` | 只在前面恰好一层受信反向代理（Caddy）时设 `true`（仅信任回环/私网来源，取 X-Forwarded-For 最后一个值，即该代理追加的那个）；**直接绑公网时不要开**，否则伪造该头可绕过登录锁定 |
| `API_KEY` | 空 | 查询 API 的 Bearer key；空则所有 API 请求都返回 401 |
| `SESSION_SECRET` | 空 | cookie 签名密钥；空则每次启动随机生成，重启后要重新登录 |

本机可以把 `DASHBOARD_PWD` 填成简单密码，**上云主机前必须换成强密码、`API_KEY` 换成随机长串**。`docker compose` 下 `DASHBOARD_PWD` 与 `API_KEY` 缺一不能启动；端口只发布到宿主机 `127.0.0.1:8081`，云主机经 HTTPS 域名访问（Phase 3）。

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

## 部署（固定公网 IP 的云主机）

1. 把主机公网 IP 加进 GPS51 后台「白名单」，openapi 才放行。
2. `docker compose up -d --build`，推送接收端监听 8080，建议前面加 HTTPS 反代。`.env` 里的 PUSH_PATH 建议设成 `/gps51/push/<随机 20 位>`，GPS51 后台填完整路径。
3. GPS51 后台「转发平台列表」新建 `Http Json` 转发，地址填 `http://<IP>:8080/gps51/push`（或反代后的 https 地址）。
4. `docker compose exec collector lutetia backfill dingtek --from 2026-08-21` 做首次回补。
5. 用 `GET /health` 和 `lutetia status` 做监控。
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

## 数据表

`device`（两源混放，`source` 区分）、`gps_position`（宽表，去重键 deviceid+updatetime）、`sensor_telemetry`（窄表，去重键 uuid+key+ts）、`sensor_attribute`、`api_call`（调用计数）。原始值不换算，单位换算在 `gps_position_v` / `sensor_telemetry_v` 视图里。
