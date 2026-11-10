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
| `lutetia import sla FILE [FILE…] [--dry-run]` | 导入 SLA 流程模板（文件名须为 `DEPOSE-Transportation` / `DEPOSE-Distribution` / `DEPOSE-MASSIVE` `.xlsx`），按模板整体替换，打印「模板名: N steps」；表头缺列、责任方不认识整批拒绝；`/api/v1/sla-templates` 读取 |
| `lutetia gps51 sync-devices` / `poll-once` | 手工同步设备、单次轮询 |
| `lutetia gps51 tracks --device ID --begin '2026-10-06 00:00:00' --end '2026-10-06 23:59:59'` | 单次历史轨迹，每设备每天限 5 次，只能手工 |

## 看板与登录

看板由 web 容器（`lutetia run --role web`，本机开发的 `all` 模式下是同进程的第二个 HTTP 监听）提供，只读（服务端渲染 + 每 60 秒局部刷新，没有任何写入口）。v0.2.0 起看板有四块：首页顶部异常总览（失联 / 低电压 / 报警 / 推送通道 / GPS51 配额 / Dingtek 登录次数，无异常显示 “All normal” / “Tout est normal”）、设备详情页（点任一设备名：井盖 7 / 30 天电压温度信号曲线 + 最近 50 条 + 属性表，GPS 最后位置小地图 + 位置表 + 里程）、位置地图页（`/dashboard/map`，12 台井盖固定点 + GPS 最后位置，`?tracks=1` 带近 7 天轨迹（按 5 分钟一格抽稀，每格留最新一点），底图用 OpenStreetMap 标准瓦片，瓦片请求单独带 `strict-origin-when-cross-origin` 引用策略、右下角标 OSM 署名）、手机宽度适配；运维看板界面只有英文与法语，按浏览器 Accept-Language 选，`?lang=en|fr` 可覆盖并记 cookie `lutetia_lang`。图表与地图库（Chart.js 4.6.1、Leaflet 1.9.4）随包自托管在 `/static/`，不走 CDN；页面带 CSP 等安全头。本机打开 `http://127.0.0.1:8081/`，未登录会跳到登录页；账号 `DASHBOARD_USER`（默认 `admin`），密码 `DASHBOARD_PWD`，登录页勾「保持登录」发 30 天会话，不勾 12 小时；三个账号（admin / orange / huawei，名字不得重复）；运维看板（`/dashboard/…` 全部页面与数据口）只许 admin 进，orange / huawei 登录后打开运维页只见一句 “The project dashboard is coming soon.”，数据口返回 403（项目看板与 `/api/v1` 另做）；升级到本版后旧会话需重新登录一次；同一 IP 连续输错 5 次锁 5 分钟（`DASHBOARD_LOGIN_LOCKOUT=off` 可关）。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `DASHBOARD_LISTEN_HOST` | `127.0.0.1` | 绑 `0.0.0.0` 必须同时设 `DASHBOARD_PWD` 与 `API_KEY`，否则启动报错退出 |
| `DASHBOARD_LISTEN_PORT` | `8081` | 监听端口 |
| `DASHBOARD_USER` | `admin` | 登录账号 |
| `DASHBOARD_PWD` | 空 | admin 登录密码，只从环境变量读；空则 admin 账号不启用 |
| `ORANGE_USER` / `ORANGE_PWD` | `orange` / 空 | Orange 的只读看板账号；密码空则该账号不启用 |
| `HUAWEI_USER` / `HUAWEI_PWD` | `huawei` / 空 | 华为的只读看板账号；密码空则该账号不启用 |
| `DASHBOARD_TRUST_PROXY` | `false` | 只在前面恰好一层受信反向代理（nginx）时设 `true`（仅信任回环/私网来源，取 X-Forwarded-For 最后一个值，即该代理追加的那个）；**直接绑公网时不要开**，否则伪造该头可绕过登录锁定 |
| `DASHBOARD_LOW_VOLT` | `3.4` | 首页异常总览的低电压阈值（V）：低于它标黄，再低 0.2 V 标红 |
| `DASHBOARD_LOGIN_LOCKOUT` | 开 | 设 `off` 关闭登录锁定（同 IP 错 5 次锁 5 分钟、全局 5 分钟 50 次锁 60 秒），仅测试阶段用；失败照常记日志 |
| `API_KEY` | 空 | 旧的查询 API Bearer key；视为名为 `legacy` 的调用方（全部范围、无 origins）；空则不存在 legacy 调用方 |
| `CALLERS_FILE` | 空 | 调用方登记文件路径（容器内 `/callers/callers.json`），格式见下节「调用方登记」；文件有任何格式错误 web 拒绝启动 |
| `LEGACY_RATE_PER_MIN` | `600` | `legacy` 调用方每分钟限额 |
| `SESSION_RATE_PER_MIN` | `600` | 浏览器会话调 `/api/v1` 的每分钟限额，按账号名各算各的 |
| `EMBED_FRAME_ANCESTORS` | `https://*.digifiber.net` | 允许用 iframe 框入 `/embed/*` 部件的来源，只用 ASCII 空格、制表符或逗号分隔（换行等其它空白不算分隔符，那一项连同后面粘着的内容会被丢弃并打 warning）；每项是 `https://<名字>.digifiber.net` 或 `https://*.<名字>` 通配（无端口、无路径、小写）；与 `CALLERS_FILE` 的来源白名单无关。不合格的项丢弃并打 warning，全部不合格时打 error、部件页仍是 `frame-ancestors 'none'`；其余页面始终禁止被框入 |
| `SESSION_SECRET` | 空 | cookie 签名密钥；`docker compose` 下**必填**（空则起不来，`host-deploy.sh` 第 2 步校验：非空、只许字母数字，生成用 `openssl rand -hex 32`）；本机不跑 compose 时可留空，此时每次启动随机生成并打 warning，重启后所有人（含 30 天会话）都要重新登录。会话签名密钥另按账号名与该账号密码派生：改某个账号的密码只让该账号的会话失效，改 `SESSION_SECRET` 让全部失效 |
| `DATABASE_RO_PASSWORD` | 空 | 只读库角色 `lutetia_ro` 的登录密码。collector 启动迁移时设到库里，web 容器用它连库（compose 里拼成 `postgresql://lutetia_ro:…@db:5432/lutetia`，所以没有 `DATABASE_RO_URL`）；`docker compose` 下必填，空则起不来；**只许字母数字**（密码直接拼进连接串，含 `/ @ # ? %` 会解析失败或连错账号；`host-deploy.sh` 第 2 步会校验），生成用 `openssl rand -hex 24`。轮换：改 `.env` 后重跑 `bash deploy/host-deploy.sh`。收回登录要手工执行 `ALTER ROLE lutetia_ro NOLOGIN PASSWORD NULL`（删掉变量不会收回） |

本机可以把 `DASHBOARD_PWD` 填成简单密码，**上云主机前必须换成强密码、`API_KEY` 换成随机长串**。`docker compose` 下 `DASHBOARD_PWD`、`API_KEY`、`DATABASE_RO_PASSWORD`、`SESSION_SECRET` 缺一不能启动；看板端口只发布到宿主机 `127.0.0.1:8081`，云主机经 HTTPS 域名访问（Phase 3）。

## 项目看板前端（`web-ui/`，`/app/`）

项目看板是 `web-ui/` 下的 Vite + Vue 单页应用，构建产物由 web 容器在 `/app/` 下托管（前端路由如 `/app/manholes` 回退到 `index.html`；`/app/assets/` 下或带扩展名的路径找不到时返回 404，不回退）。`/app` 与 `/app/*` 带单独的严格 CSP（`style-src 'self'`、`script-src 'self'`，不含 `'unsafe-inline'` / `'unsafe-eval'`）与 `X-Frame-Options: DENY`；运维看板其余路径的安全头不变。字体（IBM Plex Sans 400 / 500 / 600、Mono 400，latin + latin-ext）来自 npm 的 `@fontsource` 包、随产物自托管，不从任何外部域加载。

- 本机构建：`cd web-ui && npm ci && npm run build`（先 `vue-tsc --noEmit` 类型检查，再出 `web-ui/dist/`）；本机跑 `lutetia run` 时默认读 `./web-ui/dist`，可用 `WEB_UI_DIST` 指向别处。没构建时 web 照常启动，`/app/` 返回 503 并提示先构建，其余路由不受影响。
- 依赖：`package.json` 全部锁精确版本、`package-lock.json` 入库；加或升依赖后重新生成 lockfile，发版前跑 `npm audit --audit-level=critical`。
- 镜像：`Dockerfile` 是两阶段，`node:24-slim` 里 `npm ci && npm run build`，只把 `dist/` 拷进 `python:3.12-slim` 运行镜像的 `/app/web-ui-dist`（`WEB_UI_DIST` 已指向它）；运行镜像里没有 Node 与 `node_modules`。

| 变量 | 默认 | 说明 |
|---|---|---|
| `WEB_UI_DIST` | `web-ui/dist`（镜像内 `/app/web-ui-dist`） | 项目看板构建产物目录；目录或其中 `index.html` 不存在时 `/app/` 返回 503 |

## 嵌入部件（`/embed/*`）

三个只读部件可以用 iframe 嵌进别的网页：`/embed/fall-timeline`（移动事件时间线）、`/embed/manhole-map`（井盖地图）、`/embed/security-summary`（防盗摘要）。

- **默认允许 `https://*.digifiber.net`；配置 `EMBED_FRAME_ANCESTORS` 后以配置为准（替换默认值）**，见上面环境变量表。部件页的 `frame-ancestors` 只放行这些来源，别的站点框不进来；运维看板与 `/app/` 始终禁止被框入。
- **部件只读，不收密码。** 登录态沿用同一浏览器里项目看板的会话；未登录时部件只显示一句说明和一个登录链接（在新标签页打开 `/app/` 登录），登录后回到该标签页时部件自动重试。
- **部件怎么认宿主：** 用 `location.ancestorOrigins[0]`（Chromium / Safari 有），没有就用 `document.referrer` 的 origin；认出的 origin 不在白名单里就不发消息，也不收消息。**Firefox 没有 `ancestorOrigins`，若宿主页设了 `Referrer-Policy: no-referrer`，部件拿不到宿主 origin，就收不到部件发出的任何消息**（部件本身照常显示）。要让 Firefox 用户也收到，宿主页的 Referrer-Policy 至少要是 `strict-origin-when-cross-origin`（浏览器默认值）。
- **消息（`postMessage`，部件到宿主，只发给上一条认出的宿主 origin）：**
  - `fall-event-selected`：用户点了时间线里的一条事件。`{ type: "lutetia:fall-event-selected", v: 1, device_id, imei, started_at }` 五个字段：`device_id` 是内部设备 id（查询 API 的 `?device_id=`），`imei` 是部件上显示的名字（井盖没有名字时等于 `device_id`），`started_at` 是事件开始时间（ISO 8601）。不带位置。
  - `resize`：部件内容高度变了。`{ type: "lutetia:resize", v: 1, height }`，`height` 是向上取整的像素高度，宿主据此调 iframe 高度；有节流，高度没变不重发。
  - 宿主到部件的消息 v1 没有定义，收到会被忽略（只在控制台留一行提示）。

## 查询 API

只读 JSON，四个 GET 接口，没有任何写入接口。每个请求都要带 `Authorization: Bearer <API_KEY>`；缺头、key 错或服务端没配 `API_KEY` 一律返回 `401`，并带 `WWW-Authenticate: Bearer`。`since` / `until` 的时区偏移请用 `Z` 或把 `+` 编码为 `%2B`。

契约在 `/api/v1/openapi.json`（OpenAPI 3.1，需会话或任意有效 key，范围不限；列出全部资源、参数、响应与错误形状、每个资源要的范围），v1 只增不改；契约测试 `tests/test_api_v1_contract.py` 守着它与代码一致。

| 接口 | 参数 | 返回 |
|------|------|------|
| `GET /api/v1/devices` | 无 | `{"devices": [{source, device_id, name, device_type, expected_online, last_ts}]}` |
| `GET /api/v1/positions` | `device_id`（必填）、`since`、`until`、`limit` | `{"device_id", "count", "positions": [...]}`，每条含 `speed_kmh` 与 `speed_raw`，按 `update_time` 倒序 |
| `GET /api/v1/telemetry` | `device_id`（必填）、`key`、`since`、`until`、`limit` | `{"device_id", "count", "telemetry": [...]}`，每条含 `value_si`，按 `ts` 倒序 |
| `GET /api/v1/status` | 无 | `{"started_at", "receiver": {...} 或 null, "api_calls_24h": [...]}` |

- `since` / `until`：ISO 8601（`2026-11-01T00:00:00Z` 或 `+00:00`）或毫秒整数；解析失败返回 `400`。
- `limit`：默认 1000，范围 1 ～ 10000，越界返回 `400`；缺 `device_id` 返回 `400`。
- 时间字段统一输出 ISO 8601 UTC，带 `Z`。

`/api/v1` 另认浏览器会话：不带 `Authorization` 但带有效会话 cookie（admin / orange / huawei 任一）按账号给范围：admin 拿全部（`iot:read`、`poi:read`、`status:read`），orange / huawei 只拿 `iot:read` 与 `poi:read`，调 status 返回 `403`（运维内部状态只给 admin，Spec v1.16）。带了 `Authorization` 头就只按 key 判（key 无效、或头不是 `Bearer <非空 key>`（如 Basic、空 Bearer）即 `401`，不回落到会话）。现仅支持 `Authorization: Bearer`，没有 `X-API-Key` 头。四个接口的范围：devices / positions / telemetry 要 `iot:read`，status 要 `status:read`。状态码：`401` 无凭据或 key 无效，`403` key 有效但范围不够（响应体只有 `{"error": "forbidden"}`），`429` 超每分钟限额（带整数秒 `Retry-After`，≥ 1）。

## 调用方登记

每个外部调用方一把 key，只存 SHA-256 摘要，各自有范围、来源白名单和每分钟限额；能单独吊销、单独限流，日志只写调用方名字。登记文件放在宿主机 `~/lutetia/callers/callers.json`（`callers/*.json` 已在 `.gitignore`，不入库），`.env` 里设 `CALLERS_FILE=/callers/callers.json`（compose 把 `./callers` 只读挂到容器 `/callers`），改完 `docker compose up -d web` 重启 web 生效。仓库里的 `callers/example.json.sample` 是格式样例（值全是假的）。

```json
[
  {
    "name": "ofr",
    "key_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "scopes": ["iot:read", "poi:read"],
    "origins": ["https://ofr.digifiber.net"],
    "rate_per_min": 120
  }
]
```

| 字段 | 规则 |
|---|---|
| `name` | 必填，`[A-Za-z0-9._-]` 1～64 位，不得重复，不得叫 `legacy`（留给 `API_KEY`） |
| `key_sha256` | 必填，key 的 SHA-256 摘要，64 位小写 hex，不得重复，不得是空 key 的摘要 |
| `scopes` | 必填，非空，只能是 `iot:read` / `poi:read` / `status:read` |
| `origins` | 必填（可空数组），每项必须是 `https://<一个或多个标签>.digifiber.net`（如 `https://ofr.digifiber.net`）：不带端口、路径，不许裸 `digifiber.net`、通配符、大写；嵌入方先只限 digifiber.net 下的系统（ADR-6），不合规 web 拒绝启动并报第几项第几个来源 |
| `rate_per_min` | 必填，正整数；令牌桶容量与每分钟补充量都等于它 |

出现未知字段、未知范围、重复的 name 或 key_sha256 都会让 web 拒绝启动，报错只写第几项、哪个字段，不含 key 与摘要。

生成 key 与摘要（key 只给调用方，不写进仓库、不写进登记文件，登记文件里只放摘要）：

```bash
KEY=$(openssl rand -hex 32)
printf %s "$KEY" | sha256sum        # 取第一列填进 key_sha256
```

吊销：删掉登记文件里该调用方那一项，重启 web，它的 key 立刻返回 `401`。

CORS：请求带的 `Origin` 恰好在该调用方（已凭 key 认证）登记的 `origins` 里时，响应带 `Access-Control-Allow-Origin: <该 origin>`、`Vary: Origin`、`Access-Control-Allow-Credentials: true`；`OPTIONS` 预检只对任一调用方登记过的来源放行，方法只许 `GET`、头只许 `Authorization`；带 CORS 头的响应还带 `Access-Control-Expose-Headers: Retry-After`（浏览器能读到 429 的等待秒数）；其余来源一律没有 CORS 头，任何情况都不返回 `*`。来源按字符串逐字相等匹配（浏览器发出的 Origin 本就小写）。

日志：每个 `/api/v1` 请求一行 `api caller=<name 或 session:<账号>> resource=<path> status=<code>`，未认证记 `caller=-`；不含 key、摘要与查询参数。

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
2. 首次：在主机克隆仓库到 `~/lutetia`，并在本机把环境文件 scp 到 `hub:~/lutetia/` 下（文件名见 `.env.example` 同目录）。必须有非空的 DASHBOARD_PWD、API_KEY、PUSH_PATH、DATABASE_RO_PASSWORD、SESSION_SECRET；PUSH_PATH 建议设成 `/gps51/push/<随机 20 位>`；主机 8081 被占，加一行 `DASHBOARD_PUBLISH_PORT=18081`（nginx 配置指向它）。
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
