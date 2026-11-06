# Development Plan — Lutetia 巴黎项目 IoT 数据采集服务

> 记录项目的开发阶段划分、当前进度和剩余工作。新 session 启动先读本文件。
> 需求来源：Product-Spec.md v1.0（2026-11-06）。首版代码（提交 9d8cc7e）已覆盖 SCOPE-1 ～ SCOPE-10 的全部功能条目，但成功判据里只有 SC-6 有运行证据。本计划的主轴是把 SC-1 ～ SC-5 逐条拿到客观证据，顺手补上验证里发现的缺口；不加新功能。计划日期 2026-11-06。

## 开工前置

- 本地现状（2026-11-06 查库）：docker 容器 lutetia-pg（127.0.0.1:15433）里已有 17 台设备、141,545 行 Dingtek 遥测（REST 回补 2026-08-21 ～ 2026-11-05，12 台里 10 台有 rest 行、2 台离线机只有 WebSocket 推下来的最后值）、4 行 GPS 位置（poll）、1,105 条 api_call（Dingtek timeseries 996 次、GPS51 共 8 次）。这些是上一个 session 在 2026-11-05 20:20 ～ 20:31 UTC 跑 backfill 与短暂 `lutetia run` 留下的，没有记在任何文档里；Spec SC-1 的「当前基线 0」已经过期，Phase 1 收口时由主 Agent 按 product-spec-builder 直推档改成实数并记 CHANGELOG。
- 待定 1（volt / rsrp 系数）：押后到第一次用换算值做分析之前，本计划不碰；视图照 ÷100 / ÷10。
- 待定 2（推送非 200 的重试）：押后到 Phase 3 上线后第一周看日志；押后期间按「收到即 200、后台落库、静默 15 分钟切轮询」。
- 待定 3（目标机 Python 版本）：押后到 Phase 3 开工前由用户回答；押后期间代码按 3.9 写、部署走 python:3.12-slim 容器。Task 1.2 把「3.9 写法」从靠自觉变成机器检查，Phase 1 验收再用 python:3.9-slim 真跑一次。
- 待定 4（推送接收端 HTTPS 与鉴权）：押后到 Phase 3 在 GPS51 后台配转发之前由用户拍板；押后期间按明文 8080、不鉴权。零代码的缓解已经在：PUSH_PATH 环境变量可以把路径改成带随机段的（例如 `/gps51/push/<20 位随机串>`），Phase 3 部署时默认这么配；用户若要共享密钥校验，回本计划开 Task（改 PushReceiver._handle 校验请求头），现在不预开。
- 待定 5（推送 JSON 外层形态）：押后到 Phase 3 收到第一条真实推送；押后期间三种形态都收，认不出的打 warning 并计数——「计数」这半句代码里没有，Task 1.3 补上。
- 待定 6（GPS 位置的 GDPR 适用性）：押后到 DFX 设计之前，本计划不碰，按设备数据处理。
- `[推断]` 条目（Phase 2 演示时让用户挑错）：每日回补窗口 2 天 / 03:00 UTC；GPS51 日预算 1400 / 调用间隔 6 秒；status 失联阈值取 3 小时与 2 倍 uploadInterval 的大者；非法 JSON 返回 400 不入队；推送缺 updatetime 退用 arrivedtime 做去重键、两者都缺丢弃。
- `[默认]` 条目：换算视图的 volt ÷100、rsrp ÷10；api_call 表本版不清理。
- Spec 缺口：没有自相矛盾。实现与 Spec 的已知差异两处：待定 5 的「计数」（Task 1.3）；docker-compose 里 collector 只写了 depends_on、没等数据库就绪，首次启动 migrate 可能抢在 PostgreSQL 前面、靠 restart 重试才成功（Task 3.1）。
- 本地验证通用前置：本地环境文件里 DATABASE_URL 指向 lutetia-pg、DINGTEK_USER / DINGTEK_PWD 已填（2026-11-05 的成功调用记录证明过，不读文件核对）；state/ 里两家 token 文件存在，Dingtek 调试期只在 token 文件不存在时登录一次；GPS51 每次运行总调用 ≤ 20 次，本计划用 `GPS51_DAILY_BUDGET=20` 让代码自己兜住这条。
- REQ 覆盖：Spec 没用 `[REQ-模块-编号]`，用的是 SC-n / SCOPE-n，plan-lint 的覆盖检查会跳过；本计划在 Task 标题与验收里手工引用 SC / SCOPE 编号。

---

## Phase 1: 首版对账——对照 Spec 审查、兼容与密钥闸、推送接收端实测 ✅

交付记录（2026-11-06，用户确认完成，四态门 CONCERNS）：提交 48f97bd（Task 1.2）、060fd04（Task 1.1 HIGH 4 条修复 + Task 1.3）、5e8d5b5（复核残留 + Spec v1.1）。证据：本机 49 passed、python:3.9-slim 40 passed、SC-3 四步实测、SC-1 同区间复跑 12 台 0 new rows。残留进 progress.md 待办 #9 ～ #16。

**交付内容**：
- 首版代码对照 Spec 过一轮完整审查，HIGH 缺陷修完并复核，Medium / Low 记进 progress.md 残留。
- 测试里多一道机器闸：全部源码按 Python 3.9 语法与标准库检查、仓库里搜不到两家账号密码的前缀（SC-6 后半句）。
- 推送接收端认不出的 payload 有计数并从 /health 暴露；SC-3 在本机实测通过。
- Dingtek 回补幂等在本机拿到证据：同一区间复跑新增 0 行（SC-1 后半句）。

**验证的假设**：
- Spec 功能条目标 `[确认]` 但来源写「代码现状」的那些（会话复用、配额守护、窗口对半切、WebSocket 退避重连）确实按 Spec 描述工作——来源是转写时对代码的阅读，不是运行证据；Task 1.1 的审查报告逐条给出代码位置与「符合 / 偏差 / 存疑」。
- 代码满足「Python 3.9 写法」（Spec 兼容行 `[确认]`，目前只靠自觉）——Task 1.2 的 AST 检查全绿，且 python:3.9-slim 容器里 `lutetia --help` 与解析器测试跑通。
- 待定 5 的默认（三种推送形态都接受）在厂家转发字段表（docs/vendor/gps51/API/数据转发/forward message 转发消息.md）下成立——按该表字段手工拼一条 POST，5 秒内落库。
- 回补「同区间复跑新增 0」对本地已有的 2026-08-21 ～ 2026-11-05 数据成立——复跑一次 `--to 2026-11-05`，末行 `inserted rows: 0`。

**关键文件**：
- `lutetia/sources/gps51.py` — PushReceiver 加 unrecognised 计数（Task 1.3 唯一 owner；Task 1.1 的 HIGH 修复若也要动它，先合进 1.3 再派）
- `tests/test_compat.py` — 新建：3.9 语法 / 类型联合 / 3.10+ 标准库 AST 检查 + 密码前缀扫描
- `README.md` — 部署节监控一句补 /health 的 unrecognised 字段

**Task 清单**：
- **Task 1.1：首版对照 Spec 审查并修 HIGH 缺陷（SCOPE-1 ～ SCOPE-10）** — 对提交 9d8cc7e 的全部 `lutetia/**`、`sql/001_schema.sql`、`tests/**` 做全三 Stage 审查：Stage 0 静态（`python -m pytest -q` 全绿、`python -m compileall -q lutetia`）；Stage 1 规格（逐条对照 Spec「功能需求」「规则与例外」「关键流程」三节，每条给代码位置与 符合 / 偏差 / 存疑）；Stage 2 质量（PushReceiver 队列与消费者的并发、Gps51Client 锁内 sleep 对其它调用的阻塞、FLOW-1 失败路径 401 的退出码与日志、SIGTERM 路径的资源关闭）。HIGH 项派修后由同一轮 reviewer 复核一次。验证命令：`python -m pytest -q` 与审查报告里每条 HIGH 的复现命令
  - Business Context：首版 1600 行一次提交进库，从没有人对照 Spec 审过；Spec 又是从代码转写的，「代码等于 Spec」是循环论证，要有人独立读一遍。区分例子：Spec 规则「推送缺 updatetime 退用 arrivedtime，两者都缺丢弃」——parse_push_message 对 `{"deviceid":"x","lat":1,"lon":2}` 应返回 None，不抛异常、不入库。
  - 依赖类型：功能前置 无；验证前置 本机 pytest 可跑且 lutetia-pg 在线（DB 用例不被 skip）。
  - 证据产生者：HIGH 档——code-reviewer（fresh）出报告；HIGH 修复派 implementer（sonnet，见开发规则）；复核由同一轮 reviewer；主 Agent 亲跑 pytest 读 exit code。
- **Task 1.2：新建 tests/test_compat.py——3.9 兼容与密钥前缀机器闸（SC-6）** — 新建文件，头行 `# risk: high`。用例一：遍历 `lutetia/**/*.py` 与 `tests/*.py`，`ast.parse(src, feature_version=(3, 9))` 必须成功（本机 3.14.4 已验证该参数可用且会拒绝 match）。用例二：AST 里注解位置（FunctionDef / AsyncFunctionDef 的参数注解与 returns、AnnAssign 的 annotation）不得出现 `BinOp(op=BitOr)`。用例三：`import` / `from ... import` 不得引用固定清单里 3.10+ 才有的名字：`tomllib`、`typing.TypeAlias`、`typing.ParamSpec`、`typing.Self`、`typing.Concatenate`、`itertools.pairwise`。用例四：对 `git ls-files` 列出的每个文本文件（按 UTF-8 可解码判定，PDF 等跳过）扫描两条模式——`Huawei` 紧跟 `@`、`liwei` 紧跟 `@`——模式用 `"Hua" + "wei@"` 这种拼接方式构造，测试文件自身不含字面量。验证命令：`python -m pytest -q tests/test_compat.py`
  - Business Context：Spec 兼容行要求 3.9 写法（目标机版本未定，待定 3），SC-6 要求全仓搜不到密码前缀；两条现在都只靠自觉。区分例子：源码里写 `def f(x: int | None)` 用例二必须红；写 `Optional[int]` 必须绿。
  - 依赖类型：功能前置 无；验证前置 无（纯本地，git 可用）。
  - 证据产生者：LOW 档——implementer 自检；主 Agent 亲跑 `python -m pytest -q tests/test_compat.py` 读输出。
- **Task 1.3：PushReceiver 补 unrecognised 计数并实测 SC-3（SCOPE-3、SCOPE-9）** — 改 `lutetia/sources/gps51.py`：PushReceiver.__init__ 加 `self.unrecognised = 0`；`_consume` 里 `parse_push_payload` 返回空列表的分支加 `self.unrecognised += 1`；`_health` 返回的 JSON 加 `"unrecognised"` 字段。README 部署节第 5 步补一句 /health 返回字段清单（received / stored / rejected / unrecognised / queued / silent_sec）。验证命令（本机先起 `GPS51_DAILY_BUDGET=20 lutetia run`，PUSH_PATH 为默认）：
  ```bash
  PUSH='{"devicename":"4072400634","deviceid":"4072400634","lat":48.8566,"lon":2.3522,"arrivedtime":1793800000000,"updatetime":1793800000000,"validpoistiontime":1793800000000,"speed":0,"course":0,"altitude":35,"totaldistance":123456,"status":0,"strstatus":"","alarm":0,"stralarm":"","moving":0}'
  # 1) 合法推送：100 ms 内 200
  curl -s -o /dev/null -w '%{http_code} %{time_total}\n' -X POST localhost:8080/gps51/push -H 'Content-Type: application/json' -d "$PUSH"
  # 2) 5 秒内落库（1793800000 = 2026-11-04 13:46:40 UTC）
  sleep 5; docker exec lutetia-pg psql -U lutetia -d lutetia -tAc "select origin, update_time from gps_position where device_id='4072400634' and update_time=to_timestamp(1793800000)"
  # 3) 同一条再 POST 一次，行数不变
  curl -s -o /dev/null -X POST localhost:8080/gps51/push -H 'Content-Type: application/json' -d "$PUSH"; sleep 2
  docker exec lutetia-pg psql -U lutetia -d lutetia -tAc "select count(*) from gps_position where device_id='4072400634' and update_time=to_timestamp(1793800000)"
  # 4) 非法 JSON 返回 400 且 rejected +1；认不出的合法 JSON 返回 200 且 unrecognised +1
  curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8080/gps51/push -d '{not json'
  curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8080/gps51/push -H 'Content-Type: application/json' -d '{"hello":"world"}'
  curl -s localhost:8080/health
  ```
  预期：第 1 步打印 `200 0.0xx`（小于 0.100）；第 2 步打印 `push|2026-11-04 13:46:40+00`；第 3 步打印 `1`；第 4 步依次 `400`、`200`，/health 里 `rejected` 与 `unrecognised` 各为 1。验收后把这条假位置删掉：`delete from gps_position where device_id='4072400634' and update_time=to_timestamp(1793800000)`。
  - Business Context：待定 5 的默认行为是「认不出的打 warning 并计数」，现在只有 warning；运维上线后要靠 /health 判断第一条真实推送有没有被认出来。区分例子：POST `{"hello":"world"}` 返回 200（合法 JSON）、不落库、unrecognised 变 1；POST `{not json` 返回 400、rejected 变 1。
  - 依赖类型：功能前置 无；验证前置 本机 8080 空闲（2026-11-06 查过是空的）、lutetia-pg 在线。
  - 证据产生者：LOW 档——implementer 自检并贴四步输出；主 Agent 亲跑第 1、3 步读数字。

**验收标准**：
- `python -m pytest -q` 全绿，运行清单含 tests/test_compat.py 的 4 条用例；lutetia-pg 在线时 DB 用例不被 skip（输出里没有 `s`）；原有 18 条未破坏。
- 审查报告存在，HIGH 为 0（修完复核），Medium / Low 已写进 progress.md 残留；报告里每条「存疑」已回流 Spec 或明确判为符合。
- SC-3 四步 curl 输出与预期一致。
- Python 3.9 真跑退出码 0：`docker run --rm -e HTTP_PROXY -e HTTPS_PROXY -v "$PWD":/app -w /app python:3.9-slim sh -c "pip install -q -i https://mirrors.aliyun.com/pypi/simple '.[dev]' && lutetia --help && python -m pytest -q -p no:cacheprovider tests/test_gps51_parser.py tests/test_dingtek_parser.py tests/test_compat.py"`（镜像本机没有，首次要拉；拉不动时记「3.9 真跑未知」，不拿 AST 检查冒充）。
- SC-1 幂等：`lutetia backfill dingtek --from 2026-08-21 --to 2026-11-05` 末行 `inserted rows: 0`，日志里 12 台都是 `0 new rows`；跑完 `lutetia status` 的 `api calls last 24h` 里 dingtek login 为 0（token 复用成立）。
- Spec SC-1 基线已改成实数并记 CHANGELOG。

---

## Phase 2: 常驻采集本地长跑——WebSocket 实时、静默轮询、巡检退出码

**交付内容**：
- `lutetia/sources/dingtek.py` 拆成包，每个文件 < 300 行，公开名与 import 路径不变。
- 推送「静默」改按最近一条能认出的位置消息算；带 alarmtype 的报警转发识别后只计数不入库；/health 增加 alarms 与 message_silent_sec（Spec v1.2，用户 2026-11-06 决定）。
- `lutetia run` 在本机连续跑 2 小时：10 台在线 DC414 各有新行，最新 volt / temperature 与厂家 REST 一致，期间 Dingtek 登录 0 次（SC-2）。
- 推送静默 15 分钟后自动切轮询、碰到预算暂停 1 小时，日志与 api_call 表能对上（SC-4 本地变体，预算压到 20）。
- `lutetia status` 的失联判定有回归测试：应在线设备超时退出码 1，非在线设备不告警，uploadInterval 长的设备按 2 倍宽限（SC-5）。
- 现有 DB 用例不再改写本地真库的真实设备行（审查 M-8）。
- 只读看板 + 登录（Spec v1.3 SCOPE-11 / SC-7）：同进程第二个 HTTP 监听，登录页（admin / 环境变量密码，签名会话 cookie，错 5 次锁 5 分钟）后一页四表（设备总览含 STALE、DC414 最新读数、GPS 最后位置、采集器状态），无任何写路径，默认只绑 127.0.0.1。
- 只读查询 API（SCOPE-12 / SC-8）：`/api/v1/devices|positions|telemetry|status` 四个 GET，Bearer API key（环境变量，常量时间比较），JSON 带工程单位与原始值，limit 上限 10000。
- SIGTERM 后进程干净退出（任务取消、接收端关闭、看板关闭、连接池关闭），退出码 0。

**验证的假设**：
- 静默按位置算之后，本机没有推送时切换时机不变（启动后 15 ～ 16 分钟），长跑日志里 `silent_sec` 与 `message_silent_sec` 在只收到报警 / 认不出消息时分道扬镳——Task 2.2 用例 + 长跑中手工 POST 一条报警消息验证。
- WebSocket 订阅在小时级心跳的设备上稳定（Spec「Dingtek 实时订阅」条目，来源代码现状；2026-11-05 只连过约 2 分钟）——2 小时内 `dingtek ws` 日志有新行、断线有 `reconnecting` 与退避记录、没有连续失败。
- `[推断]` 失联阈值「3 小时与 2 倍 uploadInterval 取大」——Task 2.1 用例三：uploadInterval='2'（小时）、最新数据 3.5 小时前，不报 STALE；删掉 uploadInterval 行再跑，报 STALE。
- `[推断]` 日预算到顶暂停 1 小时（FLOW-2 失败路径）——本地预算压到 20，日志出现 `gps51 daily budget reached: 20/20; polling paused for 1h`，之后 1 小时 api_call 里 gps51 行数不再增长。
- 静默切换阈值 15 分钟（`[确认]`）——本机没有推送，启动后第 15 ～ 16 分钟出现 `gps51 push silent for 15 min -> polling every 60s`。

**关键文件**：
- `lutetia/sources/dingtek.py` — 拆成包：`dingtek/client.py`（DingtekClient 与 token 工具）、`dingtek/sync.py`（DingtekSync 与窗口常量）、`dingtek/ws.py`（DingtekWs 与退避常量），`dingtek/__init__.py` 原样 re-export 现有公开名，调用方 import 路径不变（Task 2.0 唯一 owner）
- `tests/test_status.py` — 新建：cmd_status 的失联判定与退出码回归（Task 2.1 唯一 owner）
- `lutetia/cli.py` — cmd_status 只读不改；测试若需要改它的可测性，改动归 Task 2.1 并在派单里写明
- `lutetia/parsers/gps51.py` — 新增 is_alarm_message / push_items，parse_push_payload 跳过报警项（Task 2.2 唯一 owner）
- `lutetia/sources/gps51.py` — PushReceiver 的 last_position_at / alarms / message_silent_for 与 /health 字段（Task 2.2 唯一 owner）
- `tests/test_db.py` — 改用 `test-db-*` id 并自清理，不再碰真实设备行（Task 2.3 唯一 owner）
- `lutetia/web/__init__.py`、`lutetia/web/app.py` — 新建：WebServer 类（aiohttp 第二监听、启动时的绑定 / 凭据检查、路由注册、start / stop）（Task 2.4 唯一 owner；Task 2.5 只在 app.py 加一行注册 API 路由）
- `lutetia/web/auth.py` — 新建：会话 cookie 签发 / 校验（HMAC-SHA256，12 小时）、登录失败计数与锁定、`require_session` 装饰器、`require_api_key` 装饰器（Task 2.4 唯一 owner）
- `lutetia/web/dashboard.py` — 新建：登录页 / 退出 / 看板页四表 HTML 渲染，全部 html.escape（Task 2.4 唯一 owner）
- `lutetia/web/api.py` — 新建：四个 GET JSON 接口（Task 2.5 唯一 owner）
- `lutetia/db.py` — 新增只读查询 latest_sensor_values / latest_gps_positions / list_devices / query_positions / query_telemetry 与纯函数 max_age_hours（Task 2.4 加前三个与 max_age_hours，Task 2.5 加后两个；Task 2.0 ～ 2.3 不碰它）
- `lutetia/config.py`、`lutetia/service.py`、`lutetia/cli.py`（cmd_status 改用 max_age_hours）、`docker-compose.yml`（8081 只发布到宿主机 127.0.0.1、DASHBOARD_* / API_KEY / SESSION_SECRET 环境变量）、`.env.example`、`README.md`（看板与 API 一节）— Task 2.4（README 的 API 段归 Task 2.5）
- `tests/test_web_auth.py`、`tests/test_dashboard.py` — 新建：会话签名 / 过期 / 锁定、未登录跳转、登录后四表、无写控件、非回环无密码拒启（tester，Task 2.4 验证）
- `tests/test_api.py` — 新建：401 / 200、四接口形状、limit 上限、无非 GET 路由（tester，Task 2.5 验证）

**Task 清单**：
- **Task 2.0：把 lutetia/sources/dingtek.py 拆到 300 行以内（Stage 2 文件规模项）** — 2026-11-06 复核时该文件 303 行、修完 N-3 / N-4 还会再长；按三个类拆成 `lutetia/sources/dingtek/` 包（client.py / sync.py / ws.py），`__init__.py` 把 DingtekClient、DingtekError、DingtekSync、DingtekWs 与常量 re-export，纯搬运不改逻辑；验证命令：`python -m pytest -q -p no:cacheprovider`（全绿、用例数不变）、`wc -l lutetia/sources/dingtek/*.py`（每个 < 300）、`python -c "from lutetia.sources.dingtek import DingtekClient, DingtekSync, DingtekWs, DingtekError"`
  - Business Context：dev-builder 代码精简规则「单文件不超过 300 行，超了按职责拆分」；长跑之前拆完，Phase 2 的运行证据就落在最终布局上。区分例子：拆完 `tests/test_dingtek_ws.py` 不改一行仍全绿；`git diff --stat` 里逻辑行数净变化为 0（只有文件头的 import 与 re-export）。
  - 依赖类型：功能前置 无；验证前置 无。共享写入：只有本 Task 动 dingtek 相关源码，Task 2.1 不碰。
  - 证据产生者：MEDIUM 档（搬动超 300 行）——implementer 搬，code-reviewer Stage 0 + 1 复核一次（重点：没有逻辑改动、re-export 全），主 Agent 亲跑 pytest 与 wc。
- **Task 2.1：新建 tests/test_status.py——失联判定与退出码回归（SC-5、SCOPE-7）** — 头行 `# risk: high`；复用 tests/test_db.py 的 db fixture 写法（DATABASE_URL 不可达则 skip）；每个用例用 `"test-status-" + uuid4()` 做 device_id，结束时删掉自己插的 device / sensor_telemetry / sensor_attribute 行。用例一：source=dingtek、expected_online=true、无任何遥测 → `cmd_status(cfg, args)`（args.max_age_hours=3）返回 1，capsys 输出含 `STALE` 与 `1 expected-online device(s) without recent data`。用例二：同上但 expected_online=false → 返回 0、输出无 `STALE`。用例三：expected_online=true、sensor_attribute 里 uploadInterval='2'、最新遥测 ts 为 3.5 小时前 → 返回 0；删掉 uploadInterval 行再跑 → 返回 1。用例四：Config 的 database_url 指向 127.0.0.1:1 时 `cmd_status` 抛连接异常（FLOW-3 失败路径，不许打印「全部正常」）。验证命令：`python -m pytest -q tests/test_status.py`
  - Business Context：status 的退出码是运维唯一的告警入口（FLOW-3），错报漏报都要人跑现场。区分例子：4072407783 从未上线、expected_online=false、没数据——不许算 STALE；一台在线 DC414 5 小时没数据——必须 STALE 且退出码 1。
  - 依赖类型：功能前置 无（cmd_status 已存在）；验证前置 lutetia-pg 在线；现有库里的真实设备行不动，用例只碰自己插的行。
  - 证据产生者：MEDIUM 档（新文件约 80 行）——tester（fresh，不是首版作者）写；code-reviewer Stage 0 + 1 复核一次；主 Agent 亲跑读输出。
- **Task 2.2：推送静默按位置算 + 报警转发只计数（Spec v1.2，SCOPE-3、SCOPE-9）** — `lutetia/parsers/gps51.py`：新增 `is_alarm_message(msg) -> bool`（`"alarmtype" in msg`）与 `push_items(payload) -> List[dict]`（把 parse_push_payload 里单条 / 数组 / 信封三种形态的拆项逻辑抽出来），`parse_push_payload` 改用 push_items 并跳过报警项；`lutetia/sources/gps51.py` PushReceiver：新增 `last_position_at`（_store 里 parse_push_payload 返回非空时记 monotonic）、`alarms` 计数（_store 里按 push_items 数报警项，写一行 info 带 deviceid / stralarm，不入库）、`message_silent_for()`（原 last_push_at 口径），`silent_for()` 改按 last_position_at，/health 加 `alarms`、`message_silent_sec`；README /health 字段清单补这两项；fallback_loop 不改。验证命令：`python -m pytest -q -p no:cacheprovider tests/test_gps51_parser.py tests/test_push_receiver.py`、全量 pytest、`python -m compileall -q lutetia`
  - Business Context：Spec v1.2「推送静默切轮询」「GPS51 推送接收」「健康端点」；用户 2026-11-06 决定。区分例子：POST 一条带 alarmtype 的报警消息 → 200、alarms 加一、库里不出现该行、silent_sec 不归零、message_silent_sec 归零；POST 一条位置（哪怕是重复投递、0 新增） → silent_sec 归零。
  - 依赖类型：功能前置 无；验证前置 lutetia-pg 在线。共享写入：parsers/gps51.py 与 sources/gps51.py 本 Task 唯一 owner；tests/test_push_receiver.py 与 tests/test_gps51_parser.py 由 tester 写，implementer 只读。
  - 证据产生者：MEDIUM 档（碰解析器）——tester 先按契约写用例，implementer 修绿，code-reviewer Stage 0 + 1 复核一次，主 Agent 亲跑。
- **Task 2.3：tests/test_db.py 不再改写本地真库的真实设备行（审查 M-8）** — `test_gps_insert_is_idempotent` 不再 upsert monitorlist 样例里的真实设备、不再给真实 deviceid 插位置：把 parse_lastposition 的行复制成 `device_id="test-db-" + uuid4()` 再插，并先 upsert 一条同 id 的 Device；`test_attributes_and_status` 把真实 UUID 79702a70… 换成 `test-db-` 前缀 id；两条都在 finally 里删掉自己插的 device / gps_position / sensor_attribute 行；断言不变。验证命令：`python -m pytest -q -p no:cacheprovider tests/test_db.py`，跑完 `docker exec lutetia-pg psql -U lutetia -d lutetia -tAc "select count(*) from device where device_id like 'test-db-%'"` 为 0
  - Business Context：审查 M-8 实测真设备 79702a70… 的 device.extra 被测试写成 `{}`、sensor_attribute 被样例值覆盖；dev-builder 测试隔离规则「绝不写用户的生产库」。区分例子：跑完测试后 `select extra from device where device_id='79702a70-9ba1-11f1-898a-012e63463e84'` 仍是厂家同步来的完整记录，不是 `{}`。
  - 依赖类型：功能前置 无；验证前置 lutetia-pg 在线。
  - 证据产生者：LOW 档——tester 改（它是测试文件），主 Agent 亲跑 pytest 与 psql。
- **Task 2.4：看板 + 登录（SCOPE-11、SC-7）** — 新建 `lutetia/web/` 包：`app.py` WebServer（第二 aiohttp 监听，启动时绑非回环地址而 DASHBOARD_PWD 或 API_KEY 为空则 SystemExit；`build_app()` 供测试用 aiohttp TestServer）、`auth.py`（SessionSigner HMAC-SHA256 签名 cookie 12 小时、LoginLimiter 同 IP 错 5 次锁 5 分钟、check_password 常量时间、require_session / require_api_key 装饰器）、`dashboard.py`（GET / → 302 /dashboard/；GET/POST /login；GET /logout；GET /dashboard/ 四表 HTML，全部 html.escape，60 秒 meta refresh）；`db.py` 加纯函数 `max_age_hours(default_h, upload_interval_h)` 与只读查询 `latest_sensor_values(keys)`、`latest_gps_positions()`；`cli.py` cmd_status 改用 max_age_hours；`config.py` 加 DASHBOARD_LISTEN_HOST / PORT / USER / PWD、API_KEY、SESSION_SECRET；`service.py` 在 receiver.start() 后启 WebServer、finally 里 stop；`docker-compose.yml` collector 加 DASHBOARD_LISTEN_HOST=0.0.0.0、`${DASHBOARD_PWD:?}`、`${API_KEY:?}` 与 `127.0.0.1:8081:8081`；`.env.example` 与 README 看板一节。验证命令：`python -m pytest -q -p no:cacheprovider tests/test_web_auth.py tests/test_dashboard.py`、全量 pytest、`python -m compileall -q lutetia`、`wc -l lutetia/web/*.py`（每个 < 300）
  - Business Context：Spec v1.3「看板登录」「只读看板」「看板暴露面」、规则与例外「看板与查询 API 只读」「鉴权凭据全部来自环境变量」；用户 2026-11-06「要有个登录界面」「仅能简单呈现，不能修改数据，只看」「我也好维护」。区分例子：未登录 GET /dashboard/ → 302 到 /login；密码错 5 次 → 第 6 次 429；登录后页面里一台 expected_online 且无数据的设备那行带 STALE；页面源码里除登录页外没有 `<form` / `<button` / `<input`；`lutetia/web/**` 源码里搜不到 INSERT / UPDATE / DELETE。
  - 依赖类型：功能前置 Task 2.0 ～ 2.3 已提交（732a570）；验证前置 lutetia-pg 在线；tester 与 implementer 并行，API 名按契约固定。共享写入：`lutetia/web/**`、db.py、config.py、service.py、cli.py、compose、.env.example、README 看板节归 Task 2.4；tests/test_web_auth.py、tests/test_dashboard.py 归 tester。
  - 证据产生者：HIGH 档（鉴权路径 + 超 300 行）——implementer（sonnet，见开发规则）；code-reviewer 全三 Stage；tester 独立写用例；主 Agent 亲跑 pytest，并在长跑结束后用浏览器或 curl 走一遍登录。
- **Task 2.5：只读查询 API（SCOPE-12、SC-8）** — 新建 `lutetia/web/api.py`：`register_api(app, ctx)` 注册四个 GET（`/api/v1/devices`、`/api/v1/positions`、`/api/v1/telemetry`、`/api/v1/status`），全部套 require_api_key；参数：device_id（positions / telemetry 必填）、key（telemetry 可选）、since / until（ISO 8601 或毫秒）、limit（默认 1000、上限 10000，超上限 400）；JSON 时间戳 ISO 8601 UTC 带 Z，位置带 speed_kmh 与 speed_raw，遥测带 value_si 与 value_num / value_str；`db.py` 加 `list_devices()`、`query_positions(...)`、`query_telemetry(...)`（只读，参数化）；`app.py` 加一行注册；README 加 API 一节（四个接口、curl 例子、401 说明）。验证命令：`python -m pytest -q -p no:cacheprovider tests/test_api.py`、全量 pytest、`python -m compileall -q lutetia`
  - Business Context：Spec v1.3「只读查询 API」、规则与例外「看板与查询 API 只读」；用户 2026-11-06「自己的程序，只读查询」。区分例子：不带 Authorization → 401 且 WWW-Authenticate: Bearer；`positions?device_id=4072400634&limit=10` → 10 条以内、update_time 倒序、每条含 speed_kmh；`limit=20000` → 400；路由表里没有 POST / PUT / DELETE。
  - 依赖类型：功能前置 Task 2.4（require_api_key 与 WebServer 在它里面）；验证前置 lutetia-pg 在线。共享写入：api.py 与 db.py 的两个新查询归 Task 2.5，app.py 只改注册那一行。
  - 证据产生者：MEDIUM 档（碰鉴权但复用 2.4 的装饰器，约 150 行）——implementer；code-reviewer Stage 0 + 1；tester 写 tests/test_api.py；主 Agent 亲跑并用 curl 带 key 调一次。

**验收标准**：
- `python -m pytest -q -p no:cacheprovider` 全绿，含 tests/test_status.py 4 条、Task 2.2 的解析器与接收端用例、tests/test_web_auth.py / test_dashboard.py / test_api.py；原有用例未破坏；`wc -l lutetia/sources/dingtek/*.py lutetia/web/*.py` 每个 < 300。
- 看板本机走一遍：`lutetia run` 起来后浏览器开 http://127.0.0.1:8081/ → 跳登录 → admin + 本地密码登录 → 四表都有数据、两台 GPS 设备标 STALE（本机无推送）→ 退出后再开被拦回登录页；`curl -s -o /dev/null -w '%{http_code}' localhost:8081/api/v1/devices` 为 401，带 `-H "Authorization: Bearer $API_KEY"` 为 200。
- 2 小时长跑证据（命令：`GPS51_DAILY_BUDGET=20 lutetia run 2>&1 | tee /tmp/lutetia-run.log`，2 小时后 `kill -TERM <pid>`）：
  - 日志有 `dingtek ws connected, 12 subscriptions`；
  - 查库 `select d.name, count(*) from sensor_telemetry t join device d on d.device_id=t.device_id where t.origin='ws' and t.ts > now() - interval '2 hours' and d.expected_online group by d.name` 返回 10 行、每行 ≥ 1；
  - 10 台在线设备逐台：库里 `select key, value_num from sensor_telemetry where device_id='<uuid>' and key in ('volt','temperature') order by ts desc limit 2` 与厂家 `GET https://cloud.dingtek.com/api/plugins/telemetry/DEVICE/<uuid>/values/timeseries?keys=volt,temperature`（X-Authorization 用 state/dingtek_token.json 里的 token，按名取、不打印）的数值一致；
  - `lutetia status` 的 `api calls last 24h` 里 dingtek login = 0、gps51 lastposition ≤ 20，日志里 `push silent for 15 min -> polling` 与 `daily budget reached: 20/20; polling paused for 1h` 各出现一次；
  - SIGTERM 后日志 `shutdown requested`，进程退出码 0，`ss -ltn | grep 8080` 为空。
- 长跑中发现的缺陷按 bug-fixer 修、`fix:` 提交、四步重来；修完再长跑 30 分钟确认不复发。
- `[推断]` 五条向用户演示（日志 + status 输出），用户挑错的回 Spec 改。

---

## Phase 3: 云主机上线——compose 加固、真推送与配额 24 小时实测

**交付内容**：
- docker compose 首次启动顺序可靠：collector 等 PostgreSQL 健康后再 migrate，不靠 restart 重试（SCOPE-10）。
- 固定公网 IP 云主机上 `docker compose up -d --build` 一条命令起全套，FLOW-1 第 2 ～ 4 步完成并留证据（SC-1 生产版）。
- GPS51 后台转发接通：第一条真实推送被认出并落库（SC-3 生产版），配转发前的轮询期与配好后的停轮询都有日志（SC-4）。
- 上线 24 小时后：GPS51 总调用 ≤ 1450、登录 ≤ 2、querytracks = 0；Dingtek 登录 ≤ 1；10 台 DC414 持续有新行（SC-2、SC-5 生产版）。

**验证的假设**：
- 待定 5：真实推送的外层形态是单条 / 数组 / 信封三者之一——第一条推送后 /health 的 unrecognised 为 0 且日志 `gps51 push: N positions, M new`；若 unrecognised > 0，把日志里 `keys=` 那行交回 dev-planner 迭代开解析器 Task，不在本 Phase 猜。
- 待定 2：GPS51 对非 200 的重试行为——上线第一周每天看一次日志里 400 / unrecognised 计数，有重复投递就记进 Spec 澄清记录。
- 待定 4 的默认（明文 8080 + 随机路径段）足够本版——部署时 PUSH_PATH 设成带随机段的路径；用户改主意要共享密钥时回本计划开 Task。
- 待定 3：目标机 Python 版本——走容器后与宿主机无关；用户若要求裸机 pip 部署，Phase 1 的 3.9 真跑是依据。
- GPS51 openapi 在白名单 IP 上可用（`[确认]`，但本机从没走过 openapi）——云主机上 `lutetia gps51 sync-devices` 打出 5 台，api_call 里 querymonitorlist ok=true。
- postgres:16-alpine 自带 `pg_isready`（官方镜像内置，未亲测）——`docker compose ps` 显示 db healthy 后 collector 才启动。

**关键文件**：
- `docker-compose.yml` — db 加 healthcheck，collector 的 depends_on 改带 condition（Task 3.1 唯一 owner）
- `README.md` — 部署节补 PUSH_PATH 随机段写法（Task 3.1）
- `.env.example` — PUSH_PATH 行上加随机段说明（Task 3.1）

**Task 清单**：
- **Task 3.1：docker-compose 等库就绪再启动 + 停机宽限期 + 部署文档补随机路径（SCOPE-10）** — 改 `docker-compose.yml`：db 服务加 `healthcheck`（`test: ["CMD-SHELL", "pg_isready -U lutetia -d lutetia"]`，interval 5s、timeout 3s、retries 10）；collector 的 `depends_on` 改为 `db: condition: service_healthy`；collector 加 `stop_grace_period: 40s`（推送队列清空上限是代码里的 30 秒，Docker 默认 10 秒就 SIGKILL 会把「N remaining pushes lost」那行日志都来不及打，2026-11-06 复核 N-5）。README 部署节第 2 步补「PUSH_PATH 建议设成 `/gps51/push/<随机 20 位>`，GPS51 后台填完整路径」；`.env.example` 的 PUSH_PATH 行上加同样一句注释。本 Task 不碰 Caddy（归 Task 3.2，等域名）。验证命令：`docker compose config >/dev/null`（本机 8080 被长跑占着时只跑这条）；长跑结束后 `docker compose up -d --build && sleep 20 && docker compose ps && docker compose logs collector | grep -E 'applied 001_schema.sql|lutetia running' && curl -s localhost:8080/health && curl -s -o /dev/null -w '%{http_code}' localhost:8081/login`（本机部署就是用户要的「本机部署一下」，起来后不 down，留给用户登录看板）
- **Task 3.2：Caddy HTTPS 入口（Spec v1.3 技术方向「HTTPS 入口」）** — `docker-compose.yml` 加 `caddy` 服务（`caddy:2`，ports 80 / 443，卷 caddy_data / caddy_config，挂 `./Caddyfile`），`DOMAIN` 与 `ACME_EMAIL` 环境变量；collector 的 8080 / 8081 不再发布到宿主机（Caddy 走容器网络 `collector:8080` / `collector:8081`）；新建 `Caddyfile`：`{$DOMAIN}` 站点，`handle /gps51/push/*` 与 `handle /health` → `reverse_proxy collector:8080`，`handle /dashboard/*`、`/login`、`/logout`、`/api/*`、`/` → `reverse_proxy collector:8081`；collector 环境 `DASHBOARD_TRUST_PROXY: "true"`；README 部署节改成 HTTPS + 域名的步骤（DNS A 记录 → `docker compose up -d` → 看 `docker compose logs caddy` 里证书签发成功 → GPS51 后台转发地址填 `https://<域名>/gps51/push/<随机段>`）。验证命令（云主机上，域名已解析）：`docker compose config >/dev/null`、`curl -sI https://<域名>/login | head -1` 为 `HTTP/2 200`、`curl -s https://<域名>/health`、`curl -s -o /dev/null -w '%{http_code}' http://<域名>/login` 为 308 跳 https
  - Business Context：用户 2026-11-06「放到云主机也要开 https，我要申请域名来绑定，后面通过域名来调用接口」；Spec 技术方向「HTTPS 入口（云主机）」。区分例子：`http://<域名>/login` 被 308 到 https；`https://<域名>/api/v1/devices` 不带 key 401；Caddy 日志里有 `certificate obtained successfully`。
  - 依赖类型：功能前置 Task 3.1；验证前置 用户给出域名并把 A 记录指到云主机公网 IP、80 / 443 入站放行；Caddyfile 语法落地前对 caddyserver.com/docs 核一遍（2026-11-06 只查过社区教程）。
  - 证据产生者：MEDIUM 档——implementer 写 compose + Caddyfile，code-reviewer Stage 0 + 1（重点：collector 端口不再对公网发布、XFF 信任链、/health 与推送路径转发正确）；真机验证归 /release-builder 的 deployer，主 Agent 核三件套。
  - Business Context：FLOW-1 第 1 步要求「一条命令起全套，容器先 migrate 再 run」；现在 collector 可能在 PostgreSQL 接受连接前就跑 migrate，报错后靠 restart 兜底，运维第一次看日志会以为部署坏了。区分例子：`docker compose up -d --build` 后 `docker compose logs collector` 第一行不应是 asyncpg 连接拒绝，而应是 `applied 001_schema.sql`。
  - 依赖类型：功能前置 无；验证前置 本机 docker compose v2（本机 2.40.3）、8080 空闲；本机验证会起第二个 PostgreSQL 容器，不发布端口，与 lutetia-pg 不冲突，验证完 `down -v` 清掉。
  - 证据产生者：LOW 档——implementer 自检并贴 `docker compose ps` 与 logs 输出；主 Agent 亲跑 `curl localhost:8080/health`。

**验收标准**：
- Task 3.1 本机验证命令退出码 0，logs 里 `applied 001_schema.sql` 之前没有任何连接错误。
- 部署本身走 /release-builder（用户亲自敲，HIGH 档），deployer 执行、主 Agent 独立核查三件套：云主机上 `docker compose ps` 的容器创建时间与镜像 tag、`curl http://<IP>:8080/health` 返回 JSON、live 冒烟 = `docker compose exec collector lutetia status` 退出码 0 且 17 台设备都在。验证前置：用户已备好固定公网 IP 的云主机、把该 IP 加进 GPS51 白名单、回答了待定 3 与待定 4。
- FLOW-1 第 2 ～ 3 步：`docker compose exec collector lutetia backfill dingtek --from 2026-08-21` 连跑两次，第一次 12 台各打 `N new rows`、有数据设备 ≥ 10 台；第二次末行 `inserted rows: 0`（SC-1）。
- FLOW-1 第 5 步：用户在 GPS51 后台配转发到 `http://<IP>:8080<PUSH_PATH>` 之前，服务已跑满 15 分钟并进入轮询（日志 `push silent for 15 min -> polling`，gps_position 里 origin=poll 新行）；配好后 5 分钟内日志 `gps51 push: ... new`，下一轮 `push resumed -> polling stopped`（SC-4 前半）。
- 上线 24 小时：`lutetia status` 的 `api calls last 24h`——gps51 合计 ≤ 1450、login ≤ 2、querytracks = 0；dingtek login ≤ 1；10 台在线 DC414 的 last_data_utc 都在 3 小时内，退出码 0（SC-2、SC-4 后半、SC-5 生产版）。
- 上线后 24 小时内 /health 的 unrecognised = 0；非 0 走「验证的假设」第一条的回流路径。
- 待定 2 的观察结果（有无重复投递）写进 Product-Spec.md 澄清记录。

---

## 技术栈

沿用首版，不引新依赖、不升级。版本为 2026-11-06 本机 venv 实装与 Spec 技术方向表记录的 PyPI 核对结果。

| 层级 | 技术 | 版本 | 说明 |
|------|------|------|------|
| 语言 | Python | 代码按 3.9 写法；本机 venv 3.14.4；容器 python:3.12-slim | 目标机版本未定（待定 3），Task 1.2 机器检查 3.9 写法 |
| HTTP / WebSocket | aiohttp | ≥ 3.9（本机 3.14.5） | 客户端 + 推送接收端 + Dingtek WebSocket；3.9 目标机会退到最后支持 3.9 的 3.1x |
| 数据库驱动 | asyncpg | ≥ 0.29（本机 0.32.0） | unnest 批量 upsert |
| 测试 | pytest / pytest-asyncio | ≥ 7（本机 9.2.0）/ ≥ 0.21（本机 1.4.1） | asyncio_mode=auto；DB 用例连不上库自动 skip |
| 数据库 | PostgreSQL | 16（postgres:16-alpine） | 本机 lutetia-pg 容器 127.0.0.1:15433；生产 compose 内网 db:5432 |
| 部署 | Docker Compose | v2（本机 2.40.3） | migrate → run；状态目录与数据各一卷 |
| 包管理 | pip + venv | — | `pip install -e ".[dev]"`；内网侧装包加 `-i https://mirrors.aliyun.com/pypi/simple` |

## 数据库表

五张表两个视图全部在首版 `sql/001_schema.sql` 建好，本计划不加表、不改列。

| 表名 | 所属 Phase | 用途 |
|------|-----------|------|
| `device` | 首版（已建） | 两源设备，(source, device_id) 主键，expected_online 标应在线 |
| `gps_position` | 首版（已建） | GPS 位置宽表，(device_id, update_time) 去重，raw 存原始 JSON |
| `sensor_telemetry` | 首版（已建） | Dingtek 遥测窄表，(device_id, key, ts) 去重 |
| `sensor_attribute` | 首版（已建） | Dingtek 属性，整表覆盖，status 读 uploadInterval |
| `api_call` | 首版（已建） | 每次外部调用一行，配额守护与 status 统计读它 |
| `gps_position_v` / `sensor_telemetry_v` | 首版（已建） | 换算视图，volt ÷100、rsrp ÷10 为 `[默认]` |

## 开发规则

- 每完成一个 Phase 走四步走：Code Review → 测试完整性 → 编译验证 → 功能测试；全部通过才算 Phase 完成。
- Commit message 格式：`phase-N: 简要描述`；修缺陷用 `fix:`。
- 模型：implementer 一律 sonnet，HIGH 档也不传 opus（Spec 决策依据「不用 opus」，来自 TASK.md 模型分配）；code-reviewer 按框架默认。
- 测试文件头行标 `# risk: high|medium|low`；本计划新增的两份都是 high。日常跑 high，发版前跑全量。
- GPS51 本地任何运行先设 `GPS51_DAILY_BUDGET=20`（Spec 调试期约束：每次运行 ≤ 20 次），生产 compose 不带这个覆盖。
- 密钥只按名取用，不读本地环境文件、不把 token 打进日志或回执。
- 第一个提交顺手把 `.serena/` 加进 `.gitignore`（本机工具目录，2026-11-06 发现未跟踪）。
- 决策 / 约束 / 完成随每个有代码的提交写进 progress.md（当前不存在，Phase 1 第一个 Task 收口时由 progress-recorder 建）。
- Python 3.9 写法：无 match、无 `X | Y` 类型联合、无 3.10+ 标准库；Task 1.2 之后由测试守。
