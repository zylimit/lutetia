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
- Phase 5（2026-11-07 迭代，Spec v1.8）：只切「POI 台账导入」；押后事项——Spec 待定「92 个工单没有电缆明细」「Cable List 参考重量表」「井盖真实位置」「GPS 与铜缆捆对应」都不阻塞本 Phase，按 Spec 表里「不答先按什么做」处理（导入时参考重量只收文件里已有的缓存值，#N/A 置空；无明细工单照存、不算吨数）。真实台账内容不进日志、回执与测试，只看 `--dry-run` 汇总数字。
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

## Phase 2: 常驻采集本地长跑——WebSocket 实时、静默轮询、巡检退出码 ✅

交付记录（2026-11-06，四态门 CONCERNS）：提交 732a570（Task 2.0 ～ 2.3）、5a96b8f（Task 2.4 / 2.5）、77f043e（部署 bug 修复 + Task 3.1）。长跑 12:48Z ～ 13:53Z 共 65 分钟（用户要求提前停以让出 8080 做本机部署）：WS 连接、断线 2 分钟后自动重连、10 台在线井盖 8 台有新行、Dingtek 登录 0、15 分钟准时切轮询、预算 20 到顶暂停 1 小时；GPS51 轮询因本机出口 IP 不在白名单全部 8904，SC-4「轮询落库」留到白名单加好或云主机验。看板 + 登录 + API：审查 HIGH 1 / Medium 5 全部 red-lock 修完，全量 135 passed，python:3.9-slim 81 passed。本机 compose 彩排：建表、启动回补 18,837 行、FLOW-1 第 2 ～ 3 步全量回补 130,248 行 / 复跑 0 新增、12 台有数据、登录与 API 鉴权走通。残留见 progress.md 待办 #22 ～ #29。

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

交付记录（2026-11-06 23:27，部分完成）：Task 3.1（提交 77f043e）与 Task 3.2（bd82b4f、c7d8eac）完成；/release-builder 由用户亲敲，deployer 在 `ssh hub` 上跑 `deploy/host-deploy.sh`，主 Agent 独立核三件套：容器 23:27:32 创建、镜像 23:27:28 构建（晚于 23:11:49 的提交）、HEAD c7d8eac、0 次重启；`https://iot.digifiber.net/health` 200、Let's Encrypt 证书到 2027-02-04；http→https 301、/login 200、API 无 key 401 / 带 key 200（12 台）、登录后看板 200；FLOW-1 第 2 ～ 3 步全量回补 130,644 行 / 复跑 0。标签 v0.1.0。未完成：GPS51 在主机上 8904（等用户加白名单 129.226.4.226 并配转发地址），SC-2 / SC-4 / SC-5 的 24 小时生产版证据随后看。

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
- **Task 3.2：nginx + certbot HTTPS 入口（Spec v1.3 技术方向「HTTPS 入口」，用户 2026-11-06 点名 certbot）** — 云主机实查（`ssh hub`，129.226.4.226，Ubuntu 24.04）：nginx 1.24 已在跑三个 `*.mangosv5.app` 站点、certbot 2.9 已有账号与三张证书、ufw 已放 80 / 443、宿主 8081 被一个 python 进程占着、无容器用 8080。交付：① 新建 `deploy/nginx/iot.digifiber.net.conf`（只写 80 的 server block，certbot `--nginx` 会自动补 443 与跳转）：`server_name iot.digifiber.net`；`location /gps51/push/` 与 `location = /health` → `proxy_pass http://127.0.0.1:8080`，`client_max_body_size 4m`；`location /` → `proxy_pass http://127.0.0.1:18081`；两处都传 `Host`、`X-Real-IP`、`X-Forwarded-For $proxy_add_x_forwarded_for`、`X-Forwarded-Proto $scheme`，`proxy_read_timeout 30s`；独立 access / error log。② `docker-compose.yml`：ports 改 `"127.0.0.1:${PUSH_PUBLISH_PORT:-8080}:8080"` 与 `"127.0.0.1:${DASHBOARD_PUBLISH_PORT:-8081}:8081"`（主机 .env 设 DASHBOARD_PUBLISH_PORT=18081），collector 的 `DASHBOARD_TRUST_PROXY: "true"` 保留。③ 新建 `deploy/host-deploy.sh`（幂等、`set -euo pipefail`、在主机 `~/lutetia` 下跑）：`git pull --ff-only` → 检查 `.env` 存在且含 DASHBOARD_PWD / API_KEY / PUSH_PATH 非空（只查键名与非空，不打印值）→ `docker compose up -d --build` → 装 nginx conf 到 sites-available 并软链 sites-enabled → `nginx -t` → `systemctl reload nginx` → 若 `/etc/letsencrypt/live/iot.digifiber.net` 不存在则 `certbot --nginx -d iot.digifiber.net --redirect -n --agree-tos`（主机已有 certbot 账号，不传邮箱）→ 末尾打印 `curl -sI https://iot.digifiber.net/login | head -1`、`curl -s https://iot.digifiber.net/health`、`docker compose ps`。④ README 部署节改成这套步骤（含首次要用户自己 `scp .env hub:~/lutetia/.env`、PUSH_PATH 随机段、GPS51 白名单加 129.226.4.226、转发地址 `https://iot.digifiber.net/gps51/push/<随机段>`、看板 `https://iot.digifiber.net/dashboard/`）；`.env.example` 加 DASHBOARD_PUBLISH_PORT / PUSH_PUBLISH_PORT 两行注释。验证命令（本机）：`docker run --rm -v "$PWD/deploy/nginx/iot.digifiber.net.conf":/etc/nginx/conf.d/iot.conf:ro nginx:1.24 nginx -t`（语法）、`DASHBOARD_PWD=x API_KEY=x docker compose config | grep -E '127.0.0.1:(8080|8081)'`、`bash -n deploy/host-deploy.sh`、`shellcheck deploy/host-deploy.sh`（有则跑）
  - Business Context：用户 2026-11-06「放到云主机也要开 https，我要申请域名来绑定」「certbot 搞一下」；Spec 技术方向「HTTPS 入口（云主机）」、非功能「安全」（容器端口只发布到 127.0.0.1）。区分例子：`http://iot.digifiber.net/login` 被 301 到 https；`https://iot.digifiber.net/api/v1/devices` 不带 key 401；nginx 不动既有三个站点（`nginx -t` 通过、它们的证书与 server_name 不变）。
  - 依赖类型：功能前置 Task 3.1（已完成）；验证前置 DNS 已解析（2026-11-06 `dig` 得 129.226.4.226）、主机 .env 由用户亲自放置（密钥，AI 不碰）、GPS51 白名单加主机 IP。共享写入：compose 本 Task 唯一 owner。
  - 证据产生者：MEDIUM 档——implementer 写四样产物并本机验语法，code-reviewer Stage 0 + 1（重点：端口只绑回环、转发头、脚本幂等与不打印密钥、不碰既有站点）；真机执行归 /release-builder 的 deployer（用户亲自敲），主 Agent 独立核三件套（容器创建时间与镜像、`https://iot.digifiber.net/health`、登录看板冒烟）。
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

## Phase 4: 看板增强——设备详情与曲线、异常总览、位置地图、局部刷新与手机适配 ✅

交付记录（2026-11-07 00:5x，本机四步走 CONCERNS；生产部署与浏览器走查待用户）：提交 a2d2303（Task 4.1）、76d6058（Task 4.2，alarmLevel 不判红）、afc3e58（Task 4.3）、59742ce（Task 4.4）、补测 1 笔（Phase 级 tester 5 处缺口）。四步走：① 交付清单四条实物齐全，看板之外只动 config.py / db.py 且在关键文件表内；② 四个 Task 各有 tester 先行用例 + Phase 级补缺口，全量 177 passed；③ compileall + static-check 全绿，web 零写 SQL，最大文件 179 行；④ 本机 compose 重建（镜像 00:43:01 晚于提交），13 项页面 / 数据口冒烟全 OK，未登录 302 / 401，404 带 CSP，30 天曲线数据口 10 ms、地图数据口 47 ms。审查：4.2 / 4.3 / 4.4 各一轮 Stage 0 + 1，无 HIGH，Medium 顺手修 5 处，残留见 progress.md #45 ～ #51。生产（2026-11-07 01:00，用户亲敲 /release-builder，deployer 在 hub 跑 host-deploy.sh，主 Agent 独立核三件套）：HEAD 319298b / version 0.2.0，容器 01:00:53 创建、镜像 01:00:50 构建（晚于提交 00:59:26），nginx 与证书未动；`https://iot.digifiber.net/health` 200（HTTP/2）、http→https 301；登录后首页 / 地图页 / 井盖详情 / GPS 详情 200，overview 17 台 2 项异常（两台巴黎 GPS 失联）、map 5 台 GPS（4 有位置）+ 12 井盖，7 个静态文件 200（chart.umd.js 210 KB），未登录 302 / 401，404 带 CSP。SC-9 计时从巴黎到主机：30 天曲线数据口 0.94 s，其中网络往返占大头（/health 同路径约 0.9 s，服务端本机 10 ms）。标签 v0.2.0。用户 2026-11-07 在生产地图页目视：标记、侧栏、fitBounds 正常，OSM 瓦片全部「Access blocked」（全站 Referrer-Policy same-origin 无 Referer，OSM 拒绝）→ 用户定测试阶段改直拉 Google 瓦片（Spec v1.5）→ 热修 0.2.1（5503973，红锁流程，全量 178 passed）→ 01:28 部署（容器 01:28:44 / 镜像 01:28:42 晚于提交 01:24:45，/health 200，map.js / device.js 瓦片源 Google、CSP img-src 换 Google 四域名，登录后四页 200）→ 标签 v0.2.1。残留：host-deploy.sh 自带冒烟在容器起来 2 秒时打到 502（启动竞态，脚本应等 /health 再冒烟）。用户 2026-11-07 浏览器确认 Google 瓦片正常；仍未验：曲线与 375 px 目视。Task 4.5（2026-11-07，Spec v1.6：轨迹抽稀 + SC-9 按服务端 300 毫秒）：tester 先行 tests/test_map_track.py 两用例改前红（3 ≠ 2、positions_thinned 不存在）→ implementer 加 db.positions_thinned（DISTINCT ON 5 分钟格、每格留最新、LIMIT 2500 兜底）与 data.py 常量 → reviewer Stage 0 + 1 无 HIGH 无 Medium，Low 3 条（bucket_sec=0 除零无防御、跨文件 fixture 在 --import-mode=importlib 下失效、7 天实际最多 2,017 格）；主 Agent 亲跑：全量 180 passed、compileall 过、web 零写 SQL、测试库无残留；测试库合成 7 天 × 928 点 6,496 行抽成 2,014 点，走 gps_position_pkey，执行 10 ms；本机 compose 重建 13 项冒烟全 OK，容器包版本 0.2.2，服务端计时 30 天曲线数据口 9 ms、地图数据口 65 ms（SC-9 新口径 ≤ 300 ms）。生产库与本机库 gps_position 目前各只有 4 行，真实量要等巴黎设备上线。生产（2026-11-07 20:00，用户亲敲 /release-builder；Spec v1.7 数据不出欧洲 → 整体迁到法兰克福 fra 43.165.4.9）：deployer 停 hub 采集 → pg_dump 987,247 B（sha256 两端一致）hub→fra 直传 → fra 恢复后五表 count(*) 与 hub 一致（sensor_telemetry 153,425 / api_call 3,292 / sensor_attribute 174 / device 17 / gps_position 4）→ host-deploy.sh 7 步 rc=0、证书重签（Let's Encrypt，到 2027-02-05）。主 Agent 独立核：容器 20:00:32 / 镜像 20:00:29 晚于提交 19:16:28，容器包版本 0.2.2 且 MAP_TRACK_BUCKET_SEC=300 / LIMIT=2500；DNS 43.165.4.9；/health 200、http→https 301；登录后四页 + 三数据口 200、静态 200、未登录 302 / 401、API 无 key 401、404 带 CSP；SC-9 服务端计时（主机上量）曲线 2 ms / 地图 57 ms / 首页 44 ms，跨洲端到端 0.15 s。标签 v0.2.2 = a800a8f。残留：GPS51 白名单未加 43.165.4.9（status 8904，等用户）、无 HSTS 头、hub 删除另派。

**交付内容**：
- 图表与地图库随包自托管（Chart.js 4.6.1、Leaflet 1.9.4 + 许可证文本），`/static/` 由应用自己服务；看板页加 CSP 等安全头；首页去掉整页重载，改为页面脚本每 60 秒拉会话鉴权的 JSON 数据口做局部更新；所有看板页带 viewport、窄屏不横向溢出。
- 首页顶部异常总览：失联 / 低电压 / 报警中 / 推送通道 / GPS51 配额 / Dingtek 登录次数，无异常显示「全部正常」。
- 设备详情页：井盖 7 天原始点或 30 天按小时平均的电压、温度、信号曲线 + 最近 50 条上报 + 属性表；GPS 设备最后位置小地图 + 最近 50 条位置 + 里程与运动标志。
- 位置地图页：5 台 GPS 最后位置（可选近 7 天轨迹点）+ 12 台井盖固定坐标（属性 latitude / longitude），标记弹窗链接到详情页；底图 v1.4 为 OpenStreetMap，v1.5（2026-11-07）起测试阶段直拉 Google 瓦片并标「不商用」，商用前换回（Spec 问题表）。

**验证的假设**：
- `[默认]` 30 天曲线按小时平均后每键 ≤ 720 点、详情页整体 ≤ 6 条查询且 1 秒内——Task 4.3 验收在生产库量级（14.9 万行）计时。
- `[默认]` 低电压阈值 3.4 V、配额 ≥ 80% 标黄、推送静默 > 15 分钟且在轮询标红——Task 4.2 用例固定这些数字，Spec 问题表留阈值待答。
- `[默认]` OpenStreetMap 瓦片能从用户浏览器直连（公司网络可能拦）——Task 4.4 验收时在用户浏览器开一次地图页，拦了就换底图源。→ 2026-11-07 验证结果：被 OSM 以「无 Referer」拦（全站 Referrer-Policy same-origin），用户定测试阶段换直拉 Google 瓦片（热修 0.2.1）。
- 井盖属性里的 latitude / longitude 是真实安装坐标（2026-11-06 看到属性 key 里有这两项，值没核）——Task 4.4 验收在地图上目视是否落在巴黎。

**关键文件**：
- `lutetia/web/static/vendor/{chart.umd.js,leaflet.js,leaflet.css,images/*}` + `static/LICENSES.md` + `static/app.css` + `static/app.js` — Task 4.1 唯一 owner（4.3 / 4.4 各加自己的 `device.js` / `map.js`，不改 app.js）
- `lutetia/web/data.py` — 新建：会话鉴权 JSON 数据口 overview / telemetry / positions（Task 4.1）；4.2 往 overview 里加 anomalies 字段，4.4 加 `/dashboard/data/map`
- `lutetia/web/auth.py` — 加 `require_session_json`（无会话回 401 JSON）（Task 4.1）
- `lutetia/web/app.py` — 静态路由、安全头中间件、注册 data 路由（Task 4.1）；4.2 ～ 4.4 各加一行注册，串行执行避免冲突
- `lutetia/web/dashboard.py` — 首页改：去 meta refresh、加 viewport / 样式 / 脚本、表体加 id（Task 4.1）；4.2 加异常块；4.3 把设备名改成链接
- `lutetia/web/anomalies.py` — 新建：纯函数规则（Task 4.2 唯一 owner）
- `lutetia/web/pages_device.py` — 新建（Task 4.3 唯一 owner）；`lutetia/web/pages_map.py` — 新建（Task 4.4 唯一 owner）
- `lutetia/db.py` — 加 `telemetry_series(device_id, keys, days, hourly)`、`positions_recent(device_id, days, limit)`（Task 4.1）、`manhole_locations()`（Task 4.4）
- `lutetia/config.py` — 加 `DASHBOARD_LOW_VOLT`（默认 3.4）（Task 4.2）；`pyproject.toml` package-data 加 `web/static/**`（Task 4.1）
- `tests/test_dashboard_data.py`（4.1）、`tests/test_anomalies.py`（4.2）、`tests/test_device_page.py`（4.3）、`tests/test_map_page.py`（4.4）— tester

**Task 清单**：
- **Task 4.1：看板基础——静态资源自托管 + 会话 JSON 数据口 + 局部刷新 + 手机适配 + 安全头（SCOPE-13 ④，SC-9）** — 从 jsdelivr 按精确版本下载 `chart.js@4.6.1/dist/chart.umd.js`、`leaflet@1.9.4/dist/{leaflet.js,leaflet.css,images/marker-icon.png,marker-icon-2x.png,marker-shadow.png}` 进 `lutetia/web/static/vendor/`，附 `LICENSES.md`（MIT / BSD-2 原文 + 版本号）；`pyproject.toml` package-data 加 `web/static/**`；`app.py`：`add_static("/static/", ...)`（不需登录，`show_index=False`）、安全头中间件（`Content-Security-Policy: default-src 'self'; img-src 'self' data: https://*.tile.openstreetmap.org; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: same-origin`）、注册 data 路由；`auth.py` 加 `require_session_json`（无会话 → 401 `{"error":"login required"}`）；`data.py`：`GET /dashboard/data/overview`（device_status + stale 标记 + latest_sensor_values + latest_gps_positions + receiver 计数 + call_summary(24) + `anomalies: []` 占位 + generated_at）、`GET /dashboard/data/telemetry?device_id=&keys=volt,temperature,rsrp&days=7|30`（7 天原始点，30 天 `date_trunc('hour')` 平均；days 只许 7 或 30 否则 400；每键 ≤ 1500 点）、`GET /dashboard/data/positions?device_id=&days=7`（≤ 2000 条，倒序）；`db.py` 加 `telemetry_series` 与 `positions_recent`；`dashboard.py` 首页去掉 `http-equiv=refresh`，加 `<meta name="viewport">`、`/static/app.css`、`/static/app.js`，五张表的 tbody 加 id（`tbl-devices` / `tbl-sensor` / `tbl-gps` / `tbl-receiver` / `tbl-calls`）与 `#last-refresh`；`app.js`：每 60 秒 fetch overview、用 textContent 重绘各 tbody（不拼 HTML 字符串）、失败时在 `#last-refresh` 显示「刷新失败」而不清空表；`app.css`：基础排版、≤ 600 px 表格横向滚动、STALE 行色保留。验证命令：`python -m pytest -q -p no:cacheprovider tests/test_dashboard_data.py tests/test_dashboard.py`、全量 pytest、`python -m compileall -q lutetia`、`pip install -q . --target <临时目录> --no-deps && ls <临时目录>/lutetia/web/static/vendor`（文件齐）、`grep -niE '\b(insert|update|delete|truncate|drop)\b' lutetia/web/*.py`（零命中）
  - Business Context：Spec v1.4「局部刷新与手机适配」「看板数据口」；安全底线：数据口只认会话、静态资源不含数据、API key 不进浏览器、CSP 只放本站与底图瓦片域名 瓦片。区分例子：无 cookie `GET /dashboard/data/overview` → 401 JSON；带 cookie → 200 且含 devices / receiver / anomalies 键；`days=10` → 400；`/static/vendor/chart.umd.js` 无 cookie 也 200；首页响应头含 CSP；首页 HTML 不再含 `http-equiv="refresh"`。
  - 依赖类型：功能前置 Phase 2 / 3 已提交；验证前置 lutetia-pg 在线、本机能访问 jsdelivr（2026-11-06 核过可下载）。共享写入：本 Task 唯一 owner 见关键文件。
  - 证据产生者：HIGH 档（新增会话鉴权面 + 静态服务 + 超 300 行）——implementer（sonnet）；tester 独立写 tests/test_dashboard_data.py；code-reviewer 全三 Stage（重点：数据口鉴权、CSP、静态目录不越界、聚合 SQL 参数化）；主 Agent 亲跑并在本机 compose 栈重建后用浏览器开一次。
- **Task 4.2：首页异常总览（SCOPE-13 ②）** — `lutetia/web/anomalies.py`：纯函数 `compute(devices, latest_sensor, latest_alarm_values, receiver, calls_24h, budget, low_volt) -> List[dict]`（每条 `{"level": "red"|"yellow", "kind": "stale"|"low_volt"|"alarm"|"push"|"quota"|"login", "device_id"?, "name"?, "detail": str}`；规则：失联同 status；低电压 `volt_si < low_volt`；报警 alarmFall / alarmBattery 最新值非 0（alarmLevel 不判红——2026-11-07 验收实测真库恒为 1，见 Spec 问题表）；推送 `silent_sec > PUSH_SILENCE_MIN × 60` → red；红色项按 stale → alarm → push → low_volt → quota → login 排序（失联最前）；GPS51 24h 调用 ≥ 80% 预算 → yellow，≥ 100% → red；Dingtek 24h login > 1 → red）；`db.py` 加 `latest_alarm_values(keys)`（alarm 键最新值，键名由调用方传）；`config.py` 加 `low_volt` ← DASHBOARD_LOW_VOLT 默认 3.4；`data.py` overview 填 anomalies；`dashboard.py` 首页顶部块（无异常一行「全部正常」）；`app.js` 一并刷新该块。验证命令：`python -m pytest -q -p no:cacheprovider tests/test_anomalies.py tests/test_dashboard_data.py`、全量、compileall
  - Business Context：Spec v1.4「异常总览」；首要动作「一眼看到哪台断了」。区分例子：一台 expected_online 且最新数据 5 小时前 → stale red；volt 3.35 V → low_volt；alarmFall=1 → alarm；24h gps51 调用 1200 / 预算 1400 → quota yellow。
  - 依赖类型：功能前置 Task 4.1（数据口与 app.js）；验证前置 lutetia-pg 在线。
  - 证据产生者：MEDIUM 档——implementer；tester 写 tests/test_anomalies.py（纯函数全覆盖 + 数据口含 anomalies）；code-reviewer Stage 0 + 1；主 Agent 亲跑。
- **Task 4.3：设备详情页 + 历史曲线（SCOPE-13 ①）** — `lutetia/web/pages_device.py`：`GET /dashboard/device/{source}/{device_id}`（require_session；未知设备 404 页）：井盖页含三个 canvas（volt / temperature / rsrp）、7 / 30 天切换链接、最近 50 条上报表（query_telemetry）、属性表（sensor_attribute）；GPS 页含小地图容器（Leaflet，最后位置一个标记）、最近 50 条位置表（query_positions）、里程表与 moving；`static/device.js`：按 `data-device-id` / `data-days` 调 `/dashboard/data/telemetry|positions` 画图（Chart.js line，时间轴用 ts 字符串，不引 date 适配器）；`dashboard.py` 首页设备名改成链接；`db.py` 加 `device_attributes(device_id)`。验证命令：`python -m pytest -q -p no:cacheprovider tests/test_device_page.py`、全量、compileall，并在生产库量级计时 `telemetry_series(…, 30, hourly=True)` < 300 ms
  - Business Context：Spec v1.4「设备详情页」。区分例子：`/dashboard/device/dingtek/<uuid>` 登录后 200 且含三个 canvas 与 50 行表；`/dashboard/device/gps51/4072400634` 含地图容器与里程 14790.9；`/dashboard/device/x/y` → 404；未登录 → 302 /login。
  - 依赖类型：功能前置 Task 4.1；验证前置 lutetia-pg 在线。
  - 证据产生者：MEDIUM 档——implementer；tester 写 tests/test_device_page.py；code-reviewer Stage 0 + 1（重点 HTML 转义、路径参数校验）；主 Agent 亲跑 + 浏览器开一台井盖详情看曲线。
- **Task 4.4：位置地图页（SCOPE-13 ③）** — `lutetia/web/pages_map.py`：`GET /dashboard/map`（require_session）含全屏地图容器与设备列表侧栏；`data.py` 加 `GET /dashboard/data/map`（GPS 最后位置 + 可选 `days=7` 轨迹点 + 井盖固定坐标）；`db.py` 加 `manhole_locations()`（从 sensor_attribute 的 latitude / longitude 取，缺的跳过）；`static/map.js`：Leaflet + 底图瓦片（v1.5 起测试阶段直拉 Google，attribution 必须显示）、GPS 用默认标记、井盖用圆点，弹窗含名字 / 最后时间 / 关键读数 / 详情页链接；首页导航加「地图」。验证命令：`python -m pytest -q -p no:cacheprovider tests/test_map_page.py`、全量、compileall；主 Agent 在浏览器开地图页看 OSM 瓦片能否加载、标记是否落在巴黎
  - Business Context：Spec v1.4「位置地图」。区分例子：`/dashboard/data/map` 返回 gps 数组（≤ 5 项，每项 lat / lon / update_time）与 manholes 数组（≤ 12 项）；两台巴黎 GPS 标记在 48.83, 2.26 附近；页面 HTML 含 `openstreetmap.org` 署名。
  - 依赖类型：功能前置 Task 4.1（Leaflet 已自托管、数据口框架）；验证前置 用户浏览器能连 tile.openstreetmap.org。
  - 证据产生者：MEDIUM 档——implementer；tester 写 tests/test_map_page.py；code-reviewer Stage 0 + 1；主 Agent 浏览器目视。
- **Task 4.5：地图轨迹抽稀（SCOPE-13 ③，Spec v1.6）** — `lutetia/db.py` 加 `positions_thinned(device_id, days, bucket_sec, limit)`：在 `gps_position_v` 上按 `floor(extract(epoch from update_time) / bucket_sec)` 分格，`DISTINCT ON (格)` 每格留 update_time 最新一点，格倒序 + LIMIT 兜底，全部参数化；`lutetia/web/data.py`：`MAP_TRACK_BUCKET_SEC = 300`、`MAP_TRACK_LIMIT` 改 2500 兜底，`_gps_entries` 轨迹改调 `positions_thinned`（仍倒序取、反转成时间升序给 polyline）；`positions_recent` 与 `/dashboard/data/positions` 不动；`pyproject.toml` 版本 0.2.2；README 看板节一句「轨迹按 5 分钟抽稀」。验证命令：`DATABASE_URL=postgresql://lutetia:lutetia@127.0.0.1:15433/lutetia python -m pytest -q -p no:cacheprovider tests/test_map_page.py`、全量、`python -m compileall -q lutetia`、`grep -niE '\b(insert|update|delete|truncate|drop)\b' lutetia/web/*.py`（零命中）
  - Business Context：Spec v1.6「位置地图」与决策依据「轨迹抽稀」；运维要在地图上看一台 GPS 近 7 天走过哪里，原上限 500 点按巴黎设备 928 点 / 天只盖 13 小时。区分例子：同一台插三点——T、T+60 秒（同一 5 分钟格）、T+1 小时 → `days=7` 轨迹恰 2 点，第一点是 T+60 秒那条（格内留最新）；两点相隔 1 小时的旧用例仍 2 点；`days=0` 仍空轨迹。
  - 依赖类型：功能前置 Task 4.4；验证前置 lutetia-pg 在线。
  - 证据产生者：MEDIUM 档——tester 先写 tests/test_map_page.py 抽稀用例；implementer 改 db.py / data.py；code-reviewer Stage 0 + 1（重点：SQL 参数化、时间格边界、LIMIT 兜底方向）；主 Agent 亲跑全量 + 本机 compose 冒烟量地图数据口。

**验收标准**：
- `python -m pytest -q -p no:cacheprovider` 全绿，含四个新测试文件；原有用例未破坏；`lutetia/web/*.py` 零写 SQL；每个文件 < 300 行。
- 本机 compose 栈重建后浏览器走一遍：首页顶部异常块、60 秒后 `#last-refresh` 时间变化且页面不闪、点一台井盖看到 30 天曲线、地图页看到 17 个标记、手机宽度（浏览器 375 px）无横向滚动条。
- 生产：`bash deploy/host-deploy.sh` 二跑（证书与配置都在则跳过 certbot），`https://iot.digifiber.net/static/vendor/chart.umd.js` 200，登录后四个页面各开一次；SC-9 逐条过（曲线时限 v1.6 起按服务端量：在主机上 curl 30 天曲线数据口 ≤ 300 毫秒，跨洲网络往返不计）。
- 设计规范按下一步判定跳过：表格 + 曲线 + 地图，样式跟随库默认；跳过理由与日期记 progress。

---

## Phase 5: POI 台账导入——把 Excel 台账读进自己的库（SCOPE-16，SC-12） ✅

交付记录（2026-11-08）：提交 43118d3（Task 5.2 / 5.3）、6aa7e55（release 0.3.0）；5.3 复核 ACCEPT 无 HIGH，Low 三条记 #85（排进 Task 13.3）；用户亲敲 /release-builder 部署法兰克福，真台账在 fra 正式导入。v0.3.1（2947365）另加测试阶段可关闭登录锁定。

> 用户 2026-11-07 批准「导入先于整体架构」：只做建两张表和一条命令，不含看板页面、账号、手机版、井盖挪动事件；知道表结构先定、架构设计后可能要改。需求来源 Product-Spec.md v1.8（功能需求「POI 台账导入」、数据与权限 poi / poi_cable_segment 两行、规则与例外「台账导入按表头名取列」「只有有电缆明细的工单才有计划吨数」、FLOW-5）。

**交付内容**：
- 运维执行 `lutetia import poi <xlsx 路径> [--dry-run]` → 系统读第一个工作表，按表头名取列，清洗后在一个事务里写 `poi` 与 `poi_cable_segment`，打印读到几个工单几个电缆段（几个工单没有电缆明细）、新增 / 更新 / 未变 / 台账已无各几条、清洗了什么、可疑工单号；`--dry-run` 同样解析与计数但回滚，什么都不写。
- 同一份文件再导一次，新增与更新都是 0；Excel 里没有、库里有的工单标 `in_ledger=false` 不删；任何一行出错整批回滚，库里还是上一版。
- 只用 Python 标准库读 xlsx（zipfile + xml.etree），不引新依赖；docker-compose 给 collector 加一条只读挂载 `./data/poi:/ledger:ro`，生产上用 `docker compose exec collector lutetia import poi /ledger/<文件名>` 导入。

**验证的假设**：
- `[默认]` 按表头名取列在表头重名时可靠（真文件里 Category、Min Weight、Weight(T)、Maximum Weight、Executed Weight 各出现两次，另有拼写错误的 `Recieve date`、`Length9(km)`）——证明：测试 fixture 复刻这些表头；真文件只跑 `--dry-run` 且只看汇总数字，期望 117 个工单 / 99 个电缆段 / 92 个工单没有电缆明细，数字对上才成立。
- `[默认]` 计划重量取第一个 `Weight(T)`、参考最小 / 平均 / 最大取第二组（含公式缓存值，#N/A 置空）——证明：fixture 里两列故意给不同值，断言取对；真文件 dry-run 汇总里的计划重量合计约 244 t（25 个有明细的工单）。
- `[推断]` OCC 状态的周号与日期区间能从手写文本里解析出来（格式不统一，含「S48 - S49」「2026/11/23 - 12/01」「202611/25 - 12/04」缺斜杠的笔误、「OCC ?」「Completed」）——证明：解析用例逐种格式覆盖，解析不了的返回空而不是报错，原文照存；真文件 dry-run 汇总里报「OCC 解析失败 N 条」，数字给用户看。
- `[默认]` 表结构先于整体架构定下，后面可能要改——证明：迁移只新增两张表、不碰现有五张表，改动面限于本 Phase。

**关键文件**：
- `lutetia/xlsx_min.py` — 新建：只读极简 xlsx 读取（共享字符串、数字、#N/A 类错误值、公式缓存值；单个 XML 成员解压后上限 50 MB、累计单元格数上限 `MAX_CELLS`（200 万）、含 `<!DOCTYPE` 的成员拒读、值为空的格不扩表；损坏文件统一抛 `XlsxError`，文件不存在仍抛 `FileNotFoundError`）（Task 5.1 唯一 owner）
- `lutetia/poi_import.py` — 新建：表头映射、清洗、OCC 解析、内容哈希、`parse_ledger(path) -> LedgerParse`（Task 5.1 唯一 owner）
- `lutetia/sql/003_poi.sql` — 新建：`poi`、`poi_cable_segment` 两表与索引，全部 IF NOT EXISTS（Task 5.2 唯一 owner）
- `lutetia/poi_store.py` — 新建：`apply_ledger(pool, pois, dry_run) -> Dict[str, int]` 一个事务内按内容哈希判新增 / 更新 / 未变、替换电缆段、标台账已无（Task 5.2 唯一 owner）
- `lutetia/cli.py` — 加 `import poi` 子命令与 `cmd_import_poi`（Task 5.3）
- `docker-compose.yml` — collector 加一行只读挂载；`README.md` — 命令表加一行（Task 5.3）
- `tests/xlsx_builder.py` — 新建：用 zipfile 拼合成 xlsx 的测试辅助（含重名表头、#N/A、日期序号、共享字符串）；`tests/test_xlsx_min.py`、`tests/test_poi_import.py`（Task 5.1 tester）；`tests/test_poi_store.py`、`tests/test_migrations.py` 的 EXPECTED 加 `003_poi.sql`（Task 5.2 tester）；`tests/test_cli_import.py`（Task 5.3 tester）

**Task 清单**：
- **Task 5.1：xlsx 极简读取器 + 台账映射与清洗（SCOPE-16 前半，SC-12）** — 新建 `lutetia/xlsx_min.py`：`read_first_sheet(path) -> List[List[Any]]`，用 zipfile 读 `xl/workbook.xml` 取第一个工作表、`xl/sharedStrings.xml` 还原共享字符串，按单元格 `t` 属性分 `s`（共享串）/ `str`（公式字符串）/ `e`（错误值，返回 `XlError` 字符串子类）/ `b` / 默认数字（int 或 float）；缺格补 None；超 50 MB 的 XML 成员抛 `XlsxError`；不是 zip 或没有工作表抛 `XlsxError`。新建 `lutetia/poi_import.py`：定义 `PoiRecord`、`SegmentRecord`、`LedgerParse`（`LedgerParse` 含 `pois`（PoiRecord 列表）、`rows_read`、`segment_count`、`pois_without_segments`、`cleaned`（字典：uci_normalised / trimmed_cells / na_to_empty / segment_no_cable_type / not_a_number）、`occ_unparsed`、`suspicious`（工单号列表））三个 dataclass；`PoiRecord` 带 `content_sha`（业务字段与有序段）与 `raw_sha`（工单与各段原始值）两个指纹——前者变化算「更新」，只有后者变化只刷新 raw 并计 `raw_refreshed`，不算更新（审查 M-5）（列表字段用 `field(default_factory=list)`）；`parse_ledger(path)` 读表头行，表头比较忽略大小写与多余空白，缺必需表头（UCI、POI、Subcon、Site Ville、Commun、Category、Status、Cable、type infrastructure、Length9(km)、Weight(T)、Recieve date、Planned Operation Date）抛 `LedgerError("missing column: <名>")`；重名表头按出现次序取（`Category` 第 1 个→ poi.category、第 2 个→ 电缆类别；`Weight(T)` 第 1 个→ weight_t，第 2 组 `Min Weight` / `Weight(T)` / `Maximum Weight`→ ref_min_t / ref_avg_t / ref_max_t）；POI 列非空的行开新工单，空的并入上一单，该行电缆型号、电缆类别、基础设施类型、长度、重量任一非空就产生一个电缆段（seq 从 1 起、按出现序；电缆型号为空的段 cable_type 置 None，计入 `cleaned['segment_no_cable_type']`，不丢计划重量）；UCI 转大写并去首尾空格、所有文本去首尾空格并压缩连续空白、`XlError` 与空串置 None（分别计入 cleaned）、日期序号转 `date`（1899-12-30 起算）、`Commun` 转字符串；`parse_occ(text) -> (week_from, week_to, date_from, date_to)` 解析 `S\d+` 的一到两个周号与一到两个日期（`yyyy/m/d`、缺斜杠的 `yyyymm/d`、第二个日期可省年份），解析不了的字段返回 None 且计入 `occ_unparsed`；POI 号不匹配 `^[A-Z]{3}\d{6}$` 的进 `suspicious`（不改写）；每个工单算 `content_sha`（对工单字段与有序电缆段做规范化 JSON 的 sha256，不含导入时间）；`raw` 存该工单首行与各段行按表头名收的原始值（字典，值转成 JSON 可存的类型）。验证：`python -m pytest tests/test_xlsx_min.py tests/test_poi_import.py -q -p no:cacheprovider`。
  - Business Context：运维拿到手工维护的 POI 台账 Excel，要进自己的库而不是让人每次开 Excel 数；Spec v1.8「POI 台账导入」「台账导入按表头名取列」。区分对错的例子（合成数据）：fixture 有两行——第 1 行 POI=`RNT600001`、UCI=`AURA `（尾空格）、Cable=`88-224-4`、第一个 `Weight(T)`=2.064、第二组 `Weight(T)`=2.057；第 2 行 POI 空、Cable=`88-448-4`——解析出 1 个工单（uci=`AURA`）、2 个段（seq 1、2，`weight_t` 取 2.064 而不是 2.057，`ref_avg_t` 取 2.057），cleaned.uci_normalised=1；另一个只有 POI 号、没有电缆型号的工单解析出 0 个段、`pois_without_segments` 加 1。OCC 例子：`OCC S48 - S49 2026/11/25 - 12/02` → 周 48～49、日期 2026-11-25～2026-12-02；`OCC ?` → 全 None；`202611/25 - 12/04` → 2026-11-25～2026-12-04。
  - 依赖类型：功能前置 无（纯函数，不碰数据库）；验证前置 无。共享写入：本 Task 唯一 owner 见关键文件。
  - 证据产生者：MEDIUM 档（新增文件解析器，约 250 ～ 300 行）——tester 先独立写 tests/xlsx_builder.py 与两份测试（写测者与实现者不同实例），implementer（sonnet）按测试实现；code-reviewer Stage 0 + 1（重点：Python 3.9 写法、解压大小上限、`XlError` 不被当成数值、重名表头次序）；主 Agent 亲跑 pytest 与真文件 `--dry-run` 汇总。不得把真实台账内容打进日志、回执或测试 fixture。
- **Task 5.2：迁移 003_poi.sql + 事务入库 `apply_ledger`（SCOPE-16 后半，SC-12）** — 新建 `lutetia/sql/003_poi.sql`：`poi(poi_no text PRIMARY KEY, uci text, subcon text, site_ville text, commune_code text, category text, status_raw text, occ_week_from int, occ_week_to int, occ_date_from date, occ_date_to date, received_date date, planned_op_date date, in_ledger boolean NOT NULL DEFAULT true, content_sha text NOT NULL, raw_sha text NOT NULL, raw jsonb, first_imported_at timestamptz NOT NULL DEFAULT now(), imported_at timestamptz NOT NULL DEFAULT now())`；`poi_cable_segment(poi_no text NOT NULL REFERENCES poi(poi_no) ON DELETE CASCADE, seq int NOT NULL, cable_category text, cable_type text, infra text, length_km numeric, weight_t numeric, ref_min_t numeric, ref_avg_t numeric, ref_max_t numeric, raw jsonb, PRIMARY KEY (poi_no, seq))`；`CREATE INDEX IF NOT EXISTS` 建在 `poi(uci)`、`poi(subcon)`、`poi(occ_week_from)`；全部 IF NOT EXISTS，重复执行不报错，不碰现有五张表与两个视图。新建 `lutetia/poi_store.py`：`async def apply_ledger(pool, pois: Sequence[PoiRecord], dry_run: bool = False) -> Dict[str, int]`，在 `conn.transaction()` 里：读库里现有 `(poi_no, content_sha, in_ledger)`；对每个解析出的工单——库里没有→ `new`；`content_sha` 与 `raw_sha` 都相同且 `in_ledger` 为真→ `unchanged`；仅 `raw_sha` 不同（`content_sha` 相同、`in_ledger` 为真）→ `raw_refreshed`（只刷新 poi 与各段的 raw、`raw_sha`、`imported_at`，不动业务字段与段，不算 updated）；否则→ `updated`（含「台账已无」又回来的）；new 与 updated 用 upsert 写 poi 行、删掉该工单旧电缆段后重插新段、`imported_at` 置 now()；库里有而本次文件没有的工单置 `in_ledger=false`（计入 `gone`）、不删行；`dry_run` 为真时算完计数后回滚事务、不写任何东西；任一语句出错整个事务回滚、异常向上抛；全部 SQL 参数化；numeric 列（length_km、weight_t、ref_*_t）写入前一律 `Decimal(str(值))`，不得把 float 直接传给 asyncpg（实测会存成 2.06400000000000005684… 的噪声小数，测试 `test_numeric_columns_store_clean_decimals_not_float_noise` 守这一条）。同时把 `tests/test_migrations.py` 的 `EXPECTED` 加上 `003_poi.sql`（由 tester 改）。验证：`python -m pytest tests/test_poi_store.py tests/test_migrations.py -q -p no:cacheprovider`（用 lutetia-pg，连不上自动 skip）。
  - Business Context：运维要的是「导进去、再导一次不变、坏文件不留半份」；Spec v1.8 数据与权限 poi / poi_cable_segment 两行、SC-12 反向指标「失败整批回滚」「消失的单标台账已无而不是删」。区分对错的例子：库空时导入 2 个工单（共 3 段）→ 返回 `{new: 2, updated: 0, unchanged: 0, raw_refreshed: 0, gone: 0}`；原样再导 → `{0, 0, 2, 0, 0}`；把其中一个工单的第 2 段重量改了再导 → `{0, 1, 1, 0, 0}` 且该工单仍是 2 段；导入只含第 1 个工单的文件 → 第 2 个工单 `in_ledger=false`、`gone=1`、行与段都还在；故意给一个工单两个相同 seq 的段（主键冲突）→ 抛异常、两张表行数与导入前一致。
  - 依赖类型：功能前置 Task 5.1（`PoiRecord` 等 dataclass）；验证前置 lutetia-pg 在线（127.0.0.1:15433）。共享写入：`003_poi.sql`、`poi_store.py` 本 Task 唯一 owner；`tests/test_migrations.py` 只改 EXPECTED 一处。
  - 证据产生者：MEDIUM 档（碰迁移）——tester 先独立写 tests/test_poi_store.py，implementer（sonnet）实现；code-reviewer Stage 0 + 1（重点：事务边界、SQL 参数化、迁移不碰现有表、重复执行幂等）；主 Agent 亲跑 pytest。
- **Task 5.3：命令 `lutetia import poi` + 报告 + compose 只读挂载 + README（SC-12）** — 改 `lutetia/cli.py`：`build_parser` 加 `import` 子命令组与 `poi` 子命令（位置参数 `file`、开关 `--dry-run`），`cmd_import_poi(cfg, args)`：调用 `parse_ledger`，`LedgerError` / `XlsxError` / 文件不存在 / 读出 0 个工单（`error: no POI rows in ledger`，Spec v1.9）→ 打印 `error: <原因>` 到标准错误、退出码 1、不连数据库；`poi_store.apply_ledger` 收到空列表抛 `ValueError` 作最后一道兜底；解析成功后 `Database.connect`、`apply_ledger`，打印四行（`--dry-run` 时先打印 `dry-run: nothing written`）：`read: N POI / M segments (K POI without cable detail)`、`result: A new, B updated, C unchanged, R raw refreshed, D gone from ledger`、`cleaned: uci_normalised=X trimmed_cells=Y na_to_empty=Z segment_no_cable_type=V not_a_number=Q; occ_unparsed=W`、`suspicious: <工单号逗号分隔，或 none>`；除可疑工单号外不打印任何行内容；退出码 0。改 `docker-compose.yml`：collector 的 `volumes` 加 `- ./data/poi:/ledger:ro`（不与现有 `lutetia-state:/data` 冲突）；`.dockerignore` 已排除 `docs/` 等，Dockerfile 只 COPY `lutetia/`，`data/` 不进镜像，本 Task 用 `docker compose config` 与 `docker build` 后 `docker run --rm <image> ls /app` 证明；改 `README.md` 命令表加 `lutetia import poi FILE [--dry-run]` 一行并写明生产用法与「文件不经 GitHub、不出欧洲」。验证：`python -m pytest tests/test_cli_import.py -q -p no:cacheprovider`；`docker compose config | grep -n ledger`。
  - Business Context：FLOW-5 华为项目组的小雷把新版台账放到主机上，一条命令导入、看汇总数字就知道对不对。区分对错的例子：对合成 xlsx 跑 `--dry-run` → 输出含 `dry-run: nothing written`，`poi` 表行数不变；去掉 `POI` 表头的合成文件 → 标准错误出现 `error: missing column: POI`、退出码 1、库里行数不变；正常导入两次，第二次那行是 `0 new, 0 updated, 2 unchanged`。
  - 依赖类型：功能前置 Task 5.1、5.2；验证前置 lutetia-pg 在线、本机 docker 可用。共享写入：`cli.py` 本 Task 独占。
  - 证据产生者：MEDIUM 档——tester 先独立写 tests/test_cli_import.py（用合成 xlsx 与 lutetia-pg，调 `main(argv)` 或子进程），implementer（sonnet）实现；code-reviewer Stage 0 + 1（重点：错误路径不连库、输出不泄漏行内容、compose 挂载只读）；主 Agent 亲跑 pytest，并对真实台账只跑 `--dry-run`：命令输出里的汇总数字（工单 / 段 / 无明细工单数）与本文假设的 117 / 99 / 92 对照，打印的行内容只有那四行，真实内容不进回执。
- **Task 5.4：生产导入（用户亲敲 /release-builder 之后）** — 不派 implementer。发版后由 deployer 在法兰克福生产检出 `~/lutetia`：先 `mkdir -p ~/lutetia/data/poi`（目录不存在时 Docker 会自建成 root 属主，普通用户拷不进去），再确认 compose 已带 `./data/poi:/ledger:ro` 并重建 collector；把台账文件从开发检出 `~/code/lutetia/data/poi/` 拷到生产检出 `~/lutetia/data/poi/`（同机拷贝，不经 GitHub、不出欧洲）；先 `docker compose exec collector lutetia import poi "/ledger/POI info.xlsx" --dry-run`，汇总数字与 Task 5.3 验收对上，再去掉 `--dry-run` 正式导入；用户亲眼看汇总。
  - Business Context：SC-12 的生产落地，SCOPE-16 完成的标志；真实台账只在 fra 的两个目录与生产库里，Agent 回执里只出汇总数字。区分对错的例子：正式导入后 `SELECT count(*) FROM poi` 为 117、`poi_cable_segment` 为 99，再跑一次导入输出 `0 new, 0 updated, 117 unchanged`。
  - 依赖类型：功能前置 Task 5.1 ～ 5.3 已提交推送且用户敲了 /release-builder；验证前置 生产库在线、dry-run 数字对得上。
  - 证据产生者：HIGH 档（远端写 + 生产数据）——deployer 执行，主 Agent 独立核查（生产库两表行数、二次导入 0 / 0、`curl` 看板 `/health` 仍 200、容器时间戳与镜像 tag），不以 deployer 自述为准；发版闸 release-gate 会拦。

**验收标准**：
- `python -m pytest -q -p no:cacheprovider` 全绿，含新增四个测试文件与 `test_migrations` 的 EXPECTED 更新；原有用例未破坏；新增源码文件各 < 300 行（测试文件不受此限）；Python 3.9 兼容检查（tests/test_compat.py）通过。
- 对合成 xlsx 在 lutetia-pg 上：首次导入 `N new`，原样再导 `0 new, 0 updated`，改一段重导 `1 updated`，删一单重导该单 `in_ledger=false`，毒行整批回滚；`--dry-run` 后两表行数不变。
- 对真实台账只跑 `--dry-run`：汇总为 117 POI / 99 segments / 92 POI without cable detail，计划重量合计约 244 t（25 个有明细的工单），OCC 解析失败条数如实报告；打印内容只有汇总四行。
- 代码、测试与样例文件里没有真实台账内容（`git grep -nE '[A-Z]{3}6[0-9]{5}' -- lutetia tests | grep -vE '[A-Z]{3}6000[0-9]{2}'` 无输出，即测试里的工单号只用 6000xx 段的合成号；Spec 与 progress 里用户已批准带上去的摘录除外），`data/` 仍被 `.gitignore` 排除，镜像里没有 `data/`。
- 生产导入（Task 5.4）完成后：生产库 `poi` 117 行、`poi_cable_segment` 99 行，二次导入 0 / 0 / 117；看板与采集不受影响（`/health` 200，`lutetia status` 退出码 0）。
- 设计规范按下一步判定跳过（本 Phase 无界面）；架构设计与 DFX 仍待用户看过后做，表结构可能随架构调整。

---

## 迭代 2026-11-09：Phase 6 ～ 13（项目看板、公开契约、嵌入、备份）

> 需求来源：Product-Spec.md v1.13（SCOPE-14、15、17 ～ 20，SC-10、11、13 ～ 15）、Architecture-Design.md（2026-11-08 批准，ADR-1 ～ 6）、DFX-Spec.md（2026-11-08 批准）、Design-Brief.md + DESIGN.md、设计稿 demo/index.html（2026-11-09，编码最高参照）。排序依据：DFX 优先级栈「数据不丢 > 安全 > 隐私 > 可服务 > 性能 > 成本」（用户 2026-11-08 确认）——备份排第一；读侧要先有只读角色、心跳与事件视图，公开契约才有可读的东西；页面只经 `/api/v1` 取数（ADR-5），所以契约先于页面；嵌入复用页面组件，排在页面之后；给 Orange 看之前的收口放最后。Phase 3 的 GPS51 转发（#31）是外部条件，不阻塞本迭代，Bundles 页按「暂无上报」的空态做。

**本迭代开工前置**：
- `[默认]` DFX 候选数字按候选执行，用户可否决：RTO ≤ 4 h、备份保留 14 份日备 + 8 份周备、心跳超时 90 s、恢复演练每季度一次（DFX-Spec §11 第 5 条；Phase 6、7 用到）。
- `[默认]` 备份上传工具用腾讯云官方 coscli（单个二进制，装在 fra 宿主机，安装时取最新正式版并写进本计划技术栈表）；保留期用存储桶生命周期规则在 COS 控制台配，上传凭据只给写入权限、不给删除——过期删除由 COS 自己做，泄漏的凭据删不掉备份（THR-6）。COS 宣称 S3 兼容但不保证完全一致，Task 6.3 必须实测「用这把凭据删除被拒」。
- `[默认]` SLA 参考图的数据来源：Spec 规定 SLA 表不进 Git（规则与例外「项目业务数据只在 fra 与自己的库里」），所以拆除计划页的 SLA 参考不能写死在前端；按台账导入同一套做法加 `lutetia import sla <文件>` 把三份 DEPOSE 模板导进库、经 `/api/v1/sla-templates` 读（Task 10.3）。Spec 只写了「显示模板」、没写数据怎么进库，这是实现手段不是新需求；用户若要改成别的来源，回本计划改 Task 10.3。
- `[默认]` 「Open in Ariane」链到 `https://ofr.digifiber.net/` 首页、新窗口打开；具体到某单的深链要等与 Ariane 开发方对接（OUT-14），不猜对方路由。
- `[默认]` 界面文案 EN / FR 用前端自带的两份字典（与设计稿同法），不引 vue-i18n；法语「Tourets」作 Bundles 的译名待法语使用者确认（#98），确认前照用。
- `[默认]` 前端路由用 vue-router 5.x（2026-06 已发 5.1.0，5.0 起把 unplugin-vue-router 并进核心、声明无破坏性改动；安装时核 peerDependencies 覆盖 Vue 3.5）。
- 验证前置（外部条件，只卡对应 Phase 收口、不卡开工）：Phase 6 需要用户在 COS eu-frankfurt 建私有桶、配生命周期规则、建只能写这个桶的子账号密钥，并在 fra 上亲手写好 `/etc/lutetia/backup.env`（主 Agent 不碰凭据）；Phase 8 需要用户在 fra 的环境文件里加 Orange、华为两个账号的密码变量与调用方登记文件；Phase 13 收口需要用户换强密码并删掉 `DASHBOARD_LOGIN_LOCKOUT=off`（#88）。
- 浏览器验证一律在 fra 的 `~/tools/pw`（Playwright + Chromium）上跑，本机没有 playwright（progress Notes 2026-11-09）。
- 模型与档位沿用本计划「开发规则」：implementer 一律 sonnet；碰鉴权、迁移、契约的 Task 判 HIGH，reviewer 全三 Stage 并派 tester。

---

## Phase 6: 每日备份上 COS 与第一次恢复演练（#89，DFX 第 2 维、场景 RS-1） ✅

交付记录（2026-11-09，本机四步走，四态门 CONCERNS）：提交 fb4c780（Task 6.1）、ffc8339（Task 6.2）、71eae61（Task 6.3）与本条之后的集成修复提交。6.1 HIGH 全三 Stage + tester，6.2 / 6.3 MEDIUM；6.3 审查抓到删除测试会误报 PASS（coscli 退出码不可信）已改为复查对象仍在；Phase 收口的全链路测试（tests/test_backup_chain.py，真 postgres 容器恢复真 dump）又抓到本地备份无法演练、缺表分支走不到、空 dump 残留 0 字节文件三处，已修（改按 sha256 匹配备份记录）。合成库全量 419 passed / 1 failed（#70 基线）。CONCERNS 残留：真 COS 上传、fra 上 systemd 实跑、真实恢复演练与「删除被拒」都等用户做 #99；PASS 后要在 COS 控制台核写密钥策略无删除权限；「恢复后表不存在」提示走不到（照样判失败，只是报不出表名）记 #101；shellcheck 本机未装没跑。

**交付内容**：
- fra 每天 02:30（Europe/Paris）自动把生产库 pg_dump 一份传到 COS eu-frankfurt，周日那份另存一份周备；成功与失败都记一行。
- 运维看板顶部异常总览显示「Last backup」时间，超过 26 小时没有成功备份或最近一次失败即标红。
- 用真实备份在隔离容器里恢复一次，五张表行数与备份时记录的一致，耗时写进演练记录。

**验证的假设**：
- COS 的 S3 兼容在「只写不删」的权限上真的生效（技术未知）——用备份凭据执行删除返回拒绝即成立；不成立就改成 COS 原生 CAM 策略语法重配，再测一次。
- RTO ≤ 4 h（`[候选]`）——演练从下载到行数核对完成的实测耗时 ≤ 4 h 即成立，实测数写回 DFX-Spec 第 2 维。

**关键文件**：
- `lutetia/sql/004_backup_run.sql` — 新表 `backup_run`（Task 6.1 唯一 owner）
- `deploy/backup.sh` — 宿主机上的备份脚本
- `deploy/lutetia-backup.service`、`deploy/lutetia-backup.timer` — systemd 定时（服务以 root 运行，`TimeoutStartSec=3h`）
- `deploy/restore-drill.sh` — 恢复演练脚本
- `lutetia/web/anomalies.py`、`lutetia/web/data.py` — 运维看板读 `backup_run`
- `docs/ops/restore-drill.md` — 演练记录（每次一节）

**Task 清单**：
- **Task 6.1：备份脚本与记录表** — 新建 `lutetia/sql/004_backup_run.sql`：表 `backup_run(id bigserial, started_at timestamptz, finished_at timestamptz, ok boolean, kind text check in ('daily','weekly'), object_key text, bytes bigint, sha256 text, row_counts jsonb, error text)`，幂等。新建 `deploy/backup.sh`：`docker compose exec -T db pg_dump -U lutetia -Fc lutetia` 写到 `/var/backups/lutetia/lutetia-<UTC 日期>.dump`，算 sha256，同时记五张业务表（device、gps_position、sensor_telemetry、sensor_attribute、api_call）与 poi、poi_cable_segment 的行数，用 coscli 上传到 `daily/`（周日另传 `weekly/`），本地只留最近 2 份；结束时经 `docker compose exec -T db psql` 插一行 `backup_run`（成功或失败都插，失败写 error 原因、不写凭据）；凭据只从 systemd `EnvironmentFile=/etc/lutetia/backup.env` 给的环境变量读。新建 `deploy/lutetia-backup.service` 与 `.timer`（每天 02:30 Europe/Paris，`Persistent=true`）；`deploy/host-deploy.sh` 安装并启用 timer。脚本加 `--local-only` 开关（不上传，只 dump 与记录），供没有 COS 凭据时验证。验证：本机 `bash -n deploy/backup.sh && shellcheck deploy/backup.sh`；`.venv/bin/pytest tests/test_migrations.py -q`（迁移重放两次结果相同）；fra 上 `sudo deploy/backup.sh --local-only` 后 `docker compose exec -T db pg_restore --list /…dump | head` 能列出表、`backup_run` 新增一行 ok=true。
  - Business Context：生产库是两家厂家数据的唯一存档，主机丢盘即永久丢失（Architecture §11 第一条，用户 2026-11-08 定每日 pg_dump 上 COS 法兰克福）。区分对错的例子：周日 02:30 跑完，COS 里 `daily/` 与 `weekly/` 各多一个同 sha256 的对象，`backup_run` 多一行 kind=weekly、ok=true；上传失败时也要多一行 ok=false，而不是什么都不留。
  - 依赖类型：功能前置无；验证前置——上传部分要用户建好桶与 `/etc/lutetia/backup.env`，没建好时只验 `--local-only`。`deploy/host-deploy.sh` 本 Phase 由 Task 6.1 独占修改。
  - 证据产生者：HIGH 档（迁移 + 远端写 + 凭据路径）：implementer 自检 → code-reviewer 全三 Stage → tester 写迁移幂等与脚本失败分支用例；fra 上的实跑由 deployer 在 /release-builder 里做，主 Agent 核 `backup_run` 行与 COS 对象。
- **Task 6.2：运维看板显示「Last backup」** — `lutetia/web/data.py` 的 overview 数据口加 `last_backup`（最近一行 ok=true 的 finished_at 与 bytes，以及最近一行是否失败）；`lutetia/web/anomalies.py` 加两条异常：距上次成功 > 26 h、最近一次失败；运维看板首页异常块显示。验证：`.venv/bin/pytest tests/test_backup_status.py -q`（新建，`# risk: high`，在合成库插 `backup_run` 行覆盖：从未备份、25 h 前成功、27 h 前成功、最近失败四种）。
  - Business Context：备份坏了没人看见等于没有备份（DFX 第 2 维「备份成功率每日检查」）。例子：昨天 02:30 成功、今天 02:30 失败——今天 03:00 打开运维看板必须看到红色「Backup failed」，而不是只显示昨天的成功时间。
  - 依赖类型：功能前置 Task 6.1（`backup_run` 表）。
  - 证据产生者：MEDIUM 档：implementer → code-reviewer Stage 0 + 1。
- **Task 6.3：恢复演练与「只写不删」实测** — 新建 `deploy/restore-drill.sh`：从 COS 下载最近一份日备 → 在 fra 上起一个临时 `postgres:16-alpine` 容器（独立网络、不挂生产卷）→ `pg_restore` → 对比七张表行数落在该备份 `backup_run.row_counts`（dump 前）与 `row_counts_after`（dump 后）之间（含两端；采集在 dump 期间仍在写入、各表只增不删，所以恢复值必须满足 前 ≤ 恢复 ≤ 后，越界即失败；2026-11-09 审查 ❓1 修正，原写「与 row_counts 一致」会把正常写入误报成失败）；按文件 sha256 找对应的成功记录（本地备份与周日 weekly 行都适用，且证明文件未被改动）→ 打印耗时并删除临时容器；另用备份凭据对该对象尝试一次 `coscli rm -f`，再用只读凭据确认对象仍在才算「删除被拒」（2026-11-09 审查 HIGH-1：coscli v1.0.9 会丢弃删除的返回值、先 HEAD 后删，退出码分不清「被拒」与「没删成」，所以不看退出码、只看对象还在不在；拿不准一律判失败）。读备份与删后核对都要一把只读凭据（上传凭据按设计只写不读），或演练时从 COS 控制台手动下载备份用 `--file`。结果写进 `docs/ops/restore-drill.md`（日期、备份对象、各表行数、耗时、删除测试结果）。验证：fra 上 `sudo deploy/restore-drill.sh --file <备份> --check-delete-denied` 退出码 0，输出七行「表名 前 ≤ 恢复 ≤ 后 OK」、总耗时与「delete-denied PASS」。
  - Business Context：从没恢复过的备份不算备份（DFX 场景 RS-1）。例子：dump 前 sensor_telemetry 记 160,000 行、dump 后 160,008 行，恢复出 160,003 行算通过；恢复出 159,999 行（少于 dump 前）即失败。
  - 依赖类型：功能前置 Task 6.1；验证前置：COS 里至少有一份真实日备。
  - 证据产生者：脚本由 implementer 写（MEDIUM，reviewer Stage 0 + 1）；演练实跑由 deployer 在 fra 执行，主 Agent 读完整输出与演练记录验收。

**验收标准**：
- 迁移重放两次无变化；`tests/test_backup_status.py` 与全量回归绿。
- fra 上 timer 已启用（`systemctl list-timers lutetia-backup.timer` 有下次触发时间），至少一次自动备份成功，COS 里能看到对象、`backup_run` 有对应行。
- 恢复演练七张表行数全部落在前后上下界内、耗时 ≤ 4 h；备份凭据删除后对象仍在。
- 运维看板首页显示「Last backup」。

---

## Phase 7: 采集与看板分容器、只读库角色、心跳表、挪动事件视图（ADR-1、3、4，SCOPE-18，SC-13） ✅

交付记录（2026-11-09，四态门 CONCERNS）：提交 428eede（7.1）、b6b27e1（7.2）、bca8b4b（7.3）、f61b58b（接线测试与示例环境文件）、b3757fc（release 0.5.0，tag v0.5.0）。生产 fra 三服务同镜像、collector / web 创建于 22:49:51Z 晚于提交、容器内 0.5.0、/health 200、web 以 lutetia_ro 连库写入被拒、心跳 12 秒前更新（主 Agent 独立核查）。Task 7.4：生产只读实测 alarmFall 17,590 行 → 498 个事件，平均每台每天 0.69 次（单台 0.24 ～ 1.39，近 30 天约 1.4），30 分钟窗口假设成立不改；fall_event 全量 85 ms、单台过滤 136 ms，均 ≤ 300 ms；写回 Spec v1.15 SC-13 与 DFX-Spec 第 6 维。残留 #103、#104、#106；本机合成库全量 538 passed / 1 failed（#70 预存）。

本机进度（2026-11-09）：Task 7.1 ～ 7.3 完成并提交（428eede、b6b27e1、bca8b4b），Phase 四步走本机部分通过——Code Review 各 Task 已审收口；测试完整性 tester 跨 Task 端到端 compose 冒烟 a ～ g 全过、补 tests/test_phase7_wiring.py；编译 compileall / static-check 全绿；全量 538 passed / 1 failed（#70 预存）。待上线后做 Task 7.4（生产只读实测 SC-13 基线与视图计时），之后整个 Phase 才标 ✅。

**交付内容**：
- 生产 compose 起 db、collector、web 三个服务（同一镜像）：collector 只跑采集与推送接收，web 只跑看板与 API、用只读库角色连库；web 宕掉不影响采集。
- collector 每 30 秒写一行心跳到 `collector_status`；运维看板的采集状态改读这张表，超过 90 秒没更新即标红。
- 库里有视图 `fall_event`：同一台井盖 30 分钟内的连续 alarmFall 翻转合并成一次挪动事件（开始、结束、翻转次数）。
- 用生产实测算出「合并后平均每台每天几次挪动事件」写回 Spec SC-13 基线。

**验证的假设**：
- `[默认]` 30 分钟合并窗口（SC-13）——用生产库只读跑视图，看 10 台井盖每台每天事件数是否落在「人看得过来」的量级（个位数）；若仍是几十次，把实测分布交用户定窗口，不在代码里改。
- `fall_event` 视图在 alarmFall 全量上 ≤ 300 ms（DFX 第 6 维候选）——生产库 `EXPLAIN ANALYZE` 实测。
- 只读角色真的写不进（THR-8）——web 角色执行 INSERT 被数据库拒绝。

**关键文件**：
- `lutetia/sql/005_readonly_status_events.sql` — 角色 `lutetia_ro`（NOLOGIN 起建、GRANT SELECT 与默认权限）、表 `collector_status`、视图 `fall_event`（Task 7.1 唯一 owner）
- `lutetia/db.py` — migrate 时若有 `DATABASE_RO_PASSWORD` 就给 `lutetia_ro` 设登录密码
- `lutetia/service.py` — 心跳写入；按角色只起采集或只起 web
- `lutetia/cli.py` — `lutetia run --role collector|web|all`
- `lutetia/web/dashboard.py`、`lutetia/web/anomalies.py` — 采集状态改读心跳表
- `docker-compose.yml`、`deploy/nginx-lutetia.conf`、`deploy/host-deploy.sh` — 三服务与按路径分流

**Task 清单**：
- **Task 7.1：迁移——只读角色、心跳表、挪动事件视图** — 新建 `lutetia/sql/005_readonly_status_events.sql`：`DO` 块里角色不存在才 `CREATE ROLE lutetia_ro NOLOGIN`；`GRANT USAGE ON SCHEMA public`、`GRANT SELECT ON ALL TABLES`、`ALTER DEFAULT PRIVILEGES … GRANT SELECT ON TABLES TO lutetia_ro`；表 `collector_status(id smallint primary key check (id = 1), updated_at timestamptz, version text, push_last_at timestamptz, push_count_24h int, ws_connected boolean, polling boolean, details jsonb)`；视图 `fall_event(device_id text, started_at timestamptz, ended_at timestamptz, flips int)`：从 `sensor_telemetry` 取 key='alarmFall' 的点，按设备排序，相邻非零翻转间隔 ≤ 30 分钟归同一事件（窗口用一个常量写在视图定义里，注释注明来源 SC-13）。`lutetia/db.py` 的 migrate 末尾：环境变量 `DATABASE_RO_PASSWORD` 非空时执行 `ALTER ROLE lutetia_ro LOGIN PASSWORD`（用 `quote_literal` 拼、日志只打「ro password set」）。验证：`.venv/bin/pytest tests/test_migrations.py tests/test_fall_event.py -q`（`test_fall_event.py` 新建 `# risk: high`：合成遥测覆盖「两次翻转相隔 29 分钟算一次」「相隔 31 分钟算两次」「alarmFall 由 0 变非 0 的每一次都落进某个事件」三例）；`tests/test_readonly_role.py`（新建 `# risk: high`）：以 `lutetia_ro` 连合成库执行 INSERT 被拒。
  - Business Context：挪动事件规则只在视图里一处（ADR-3、DFX 归一化）；web 用只读角色是「看板只读」从约定变成数据库强制（Pinned、THR-8）。例子：同一台井盖 08:00、08:20、08:45 三次翻转——08:00 与 08:20 是一个事件（flips=2），08:45 距 08:20 只有 25 分钟也并入，得到一个 08:00 ～ 08:45、flips=3 的事件；若第三次在 08:51 则是两个事件。
  - 依赖类型：功能前置无。
  - 证据产生者：HIGH 档（迁移 + 鉴权边界）：implementer → code-reviewer 全三 Stage → tester 补视图边界用例。
- **Task 7.2：心跳写入与看板改读心跳** — `lutetia/service.py` 加一个每 30 秒的任务，把推送最后到达时间、近 24 小时推送条数、Dingtek WebSocket 是否连着、GPS51 是否在轮询、包版本 upsert 进 `collector_status`（写失败只打 warning、不影响采集）；`lutetia/web/dashboard.py` 与 `lutetia/web/anomalies.py` 不再读 collector 进程内存，改读该表，`updated_at` 早于 90 秒前即在异常块显示「Collector heartbeat stale」。顺手把 `lutetia/__init__.py` 的 `__version__` 改成从包元数据读（#86），心跳里的 version 用它。验证：`.venv/bin/pytest tests/test_heartbeat.py tests/test_dashboard.py tests/test_anomalies.py -q`（`test_heartbeat.py` 新建 `# risk: high`：60 秒前、91 秒前、从无心跳三种）。
  - Business Context：web 与 collector 分容器后不能再伸手读对方内存（ADR-4、迪米特）；采集挂了要第二天打开就看见（DFX 场景 SV-1）。例子：collector 容器 02:00 退出，03:00 打开运维看板，异常块必须有红色心跳过期，而不是显示 02:00 前最后一次的「WS connected」。
  - 依赖类型：功能前置 Task 7.1（`collector_status` 表）。
  - 证据产生者：MEDIUM 档：implementer → code-reviewer Stage 0 + 1。
- **Task 7.3：分容器与按路径分流** — `lutetia/cli.py` 的 `run` 加 `--role collector|web|all`（默认 all 保持本地开发不变）；`lutetia/service.py` 按角色只起对应部分；`docker-compose.yml` 改为 db、collector（`lutetia migrate && lutetia run --role collector`）、web（`lutetia run --role web`，`DATABASE_URL` 指向 `lutetia_ro`；`depends_on` 只要 collector 已启动、不等健康，首次上线连库失败靠 restart 自愈——2026-11-09 审查 N-1 改正：原写「等 collector 健康后启动」与 ADR-4「web 不依赖 collector 存活」冲突，collector 起不来时看板会跟着断）三个服务，同一镜像；`deploy/nginx-lutetia.conf`：`/gps51/push` 与 `/health` 转 collector，其余转 web；`deploy/host-deploy.sh` 同步；README 环境变量表加 `DATABASE_RO_PASSWORD`、`DATABASE_RO_URL`。验证：本机 `docker compose up -d --build` 后 `docker compose ps` 三服务 healthy；`curl -s localhost:8080/health` 有 JSON；`docker compose stop web` 后推送接收端仍回 200（`curl -X POST` 合成推送）、`collector_status.updated_at` 继续前进。
  - Business Context：看板被刷爆或崩溃时推送照收（Architecture 场景 3、ADR-1）。例子：web 容器 OOM 退出的 10 分钟里，GPS 推送照样入库、心跳照样更新；web 恢复后看到这 10 分钟的数据。
  - 依赖类型：功能前置 Task 7.1、7.2。`docker-compose.yml` 与 `deploy/host-deploy.sh` 本 Phase 由 Task 7.3 独占修改。
  - 证据产生者：HIGH 档（部署拓扑 + 鉴权凭据路径）：implementer → code-reviewer 全三 Stage → tester 跑 compose 冒烟；生产切换走 /release-builder，主 Agent 核三件套与三服务各自的容器创建时间。
- **Task 7.4：SC-13 基线与视图计时（文档 Task，主 Agent 执行）** — 部署后在 fra 用只读角色跑 `SELECT device_id, count(*)/days …` 得到每台每天平均事件数，`EXPLAIN ANALYZE SELECT * FROM fall_event` 记耗时；数字写回 Product-Spec SC-13「当前基线」并成对记 CHANGELOG（直推档），DFX-Spec 第 6 维基线同步。验证：Spec 与 CHANGELOG diff 里有实测数与测量时间。
  - Business Context：SC-13 要求「导入后用库里实测给出合并后平均每台每天几次写回本行基线」。例子：若实测 10 台平均每台每天 0.4 次，基线写「0.4 次 / 台 / 天（2026-11-xx 生产只读实测）」。
  - 依赖类型：功能前置 Task 7.3 已上线。
  - 证据产生者：主 Agent 亲跑只读查询并贴原始输出。

**验收标准**：
- 全量回归绿；新用例四份全绿。
- 本机与生产都是三服务；停 web 不影响推送入库与心跳。
- 运维看板采集状态来自心跳表，停 collector 90 秒后标红。
- `fall_event` 实测 ≤ 300 ms；SC-13 基线已写回 Spec。

---

## Phase 8: 公开契约 `/api/v1`、调用方登记与三个账号（SCOPE-17、19，SC-14，THR-1） ✅

2026-11-11 随 v0.6.0 上线（CONCERNS：orange / huawei 账号待用户在生产环境文件加密码，#100）。

本机进度（2026-11-10）：Task 8.1 ～ 8.4 完成并提交（636a7a7、bf3bd8c、8e06518、f3d4706），Phase 四步走本机部分通过——各 Task 审查收口；tester 端到端 compose 冒烟 a ～ i 全过（三账号与 remember Max-Age=2592000、orange 运维口 403、ariane 只读 iot 范围 403 / 429 Retry-After / CORS 只对 ofr.digifiber.net、legacy 四接口 200、openapi.json 未认证 401、六个列表服务端中位数 2.7 ～ 6.5 ms、compose 日志坐标与密钥命中 0、改 orange 密码只失效 orange）；全量 765 passed / 1 failed（#70 预存）。待上线（用户先做 #100）后整个 Phase 标 ✅。

**交付内容**：
- admin、orange、huawei 三个账号都能登录（密码各在环境变量）；勾「Keep me signed in」发 30 天会话，不勾 12 小时；改任一密码后该账号所有会话立即失效。
- 调用方登记文件里每个调用方一把 key（只存摘要）、一组只读范围、来源白名单、每分钟限额；超范围 403、无 key 401、超限 429 带 `Retry-After`；日志写调用方名字不写 key。
- `/api/v1` 新增项目看板要用的资源：汇总、井盖（含状态）、挪动事件、铜缆捆位置与轨迹、POI 工单与电缆段、采集状态；统一信封 `items` / `as_of` / `next`，游标分页；原有四个接口行为不变。
- `/api/v1/openapi.json` 列出全部资源；契约测试拿它校验每个资源的响应。

**验证的假设**：
- 原有四个接口在新鉴权下对现有调用者兼容（LSP）——用旧 `API_KEY` 调四个接口的响应与改造前逐字段一致。
- 同一时刻自家页面与调用方拿到的挪动事件数一致（SC-14）——会话与 key 两种方式调 `/api/v1/fall-events` 计数相同。

**关键文件**：
- `lutetia/config.py` — 三账号与调用方登记文件路径（Task 8.1 唯一 owner）
- `lutetia/web/auth.py` — 三账号登录、30 天会话、按账号派生签名密钥
- `lutetia/web/callers.py` — 新建：调用方登记读取、key 摘要比对、范围、限流、CORS
- `lutetia/web/api_v1/` — 新建包：`__init__.py`（路由注册）、`envelope.py`（信封与游标）、`resources.py`（各资源处理函数）
- `lutetia/web/api.py` — 原四个接口迁入新包后保留兼容入口
- `lutetia/web/openapi.json` — OpenAPI 3.1 契约
- `README.md` — 环境变量表与调用方登记文件格式

**Task 清单**：
- **Task 8.1：三个账号与 30 天会话（SCOPE-17）** — `lutetia/config.py` 加 `ORANGE_USER` / `ORANGE_PWD`、`HUAWEI_USER` / `HUAWEI_PWD`（缺密码的账号不启用，启动日志说明启用了哪几个，不打密码）；`lutetia/web/auth.py`：登录按三账号逐个常量时间比对，会话里记账号名，`remember=1` 时有效期 30 天否则 12 小时，签名密钥由 `SESSION_SECRET` 与该账号密码派生（改密码即失效）；`/login` 表单加「Keep me signed in for 30 days」；运维看板页头显示当前账号。验证：`.venv/bin/pytest tests/test_web_auth.py -q`（加用例：orange 登录成功、改 orange 密码后旧 cookie 401 而 huawei 会话仍有效、remember 的 Max-Age = 2592000）。
  - Business Context：Orange 与华为各用各的账号、看同样的数据（Spec 功能需求「项目看板登录」，OUT-10 不做行级权限）。例子：华为改了密码，Orange 正在手机上开着的看板不受影响；华为旧手机下一次请求就被要求重新登录。
  - 依赖类型：功能前置无；验证前置：生产要用户在环境文件里加两个账号的密码变量。
  - 证据产生者：HIGH 档（鉴权）：implementer → code-reviewer 全三 Stage → tester。
- **Task 8.2：调用方登记、范围、限流、CORS（SCOPE-19，THR-1）** — 新建 `lutetia/web/callers.py`：读 `CALLERS_FILE`（JSON 数组，每项 `name`、`key_sha256`、`scopes`（`iot:read` / `poi:read` / `status:read` 的子集）、`origins`、`rate_per_min`），启动时校验格式、有错拒绝启动；旧 `API_KEY` 视为名为 `legacy` 的调用方、拥有全部范围（兼容）；请求带 `Authorization: Bearer` 时按摘要常量时间查找；每个调用方一个令牌桶，超限 429 + `Retry-After`；登记了 origins 的调用方对其来源返回 CORS 头（带凭据），其余来源不返回；每次 API 请求日志一行 `api caller=<name> resource=<path> status=<code>`。浏览器会话视为拥有全部只读范围。验证：`.venv/bin/pytest tests/test_callers.py -q`（新建 `# risk: high`：无 key 401、范围外 403、第 N+1 次 429 且有 Retry-After、白名单外 Origin 无 CORS 头、日志行不含 key 原文、登记文件格式错误时启动失败）。
  - Business Context：每个调用方能单独吊销、单独限流，日志看得出是谁调的（Spec 功能需求「调用方登记」、DFX 场景 S-1）。例子：Ariane 只登记了 `iot:read`，它调 `/api/v1/pois` 必须 403、响应体里没有任何工单数据；删掉 Ariane 那一行并重启 web，它的 key 立刻 401。
  - 依赖类型：功能前置无（与 Task 8.1 并行无共写文件；`lutetia/config.py` 由 8.1 独占，本 Task 只在 `callers.py` 内读环境变量名）。
  - 证据产生者：HIGH 档：implementer → code-reviewer 全三 Stage → tester。
- **Task 8.3：新资源与信封（SCOPE-19、SC-10 的数据面）** — 新建 `lutetia/web/api_v1/`：`envelope.py`（列表信封 `{"items", "as_of", "next"}`、游标编码、`limit` 默认 100 上限 1000、快照资源加 `source`）；`resources.py` 注册 GET：`/api/v1/summary`（井盖总数、24 h 挪动数含正在挪动、离线数、在线安静数——三项互斥合计等于总数，progress Decisions 2026-11-09；铜缆捆追踪器数与在线数、最后位置时间；工单数、有明细工单数、计划吨数、无重量工单数）、`/api/v1/manholes`（每台：状态 quiet / moved / moving / offline、电压、信号、最后上报、属性坐标并带 `location_verified: false`）、`/api/v1/fall-events?since=&until=&device_id=`（读 `fall_event` 视图，正在进行的事件 `ended_at` 为 null）、`/api/v1/bundles`（每台最后位置）、`/api/v1/bundles/{device_id}/track?days=7`（沿用现有抽稀）、`/api/v1/pois`（筛选参数 uci、subcontractor、commune、category、network、cable_type；`source: "excel-snapshot"`）、`/api/v1/pois/{poi_no}/segments`、`/api/v1/collector-status`（读心跳表）；范围：manholes / fall-events / bundles 要 `iot:read`，pois 要 `poi:read`，collector-status 要 `status:read`；原 `/api/v1/devices` 等四个接口迁进本包、路径与字段不变。验证：`.venv/bin/pytest tests/test_api.py tests/test_api_v1_resources.py -q`（新建 `# risk: high`，合成库覆盖每个资源的正常、空、分页翻到底 `next` 为 null、summary 三项合计等于井盖总数）；本机计时：`curl -w '%{time_total}'` 每个列表 ≤ 0.3 s。
  - Business Context：自家页面、嵌入部件、外部系统都只经这一组接口取数（ADR-5），总览上的数字点下去要能到明细（SC-10）。例子：生产当前 12 台井盖里 2 台离线、1 台正在挪动、2 台 24 h 内动过——summary 必须给 moved=3、offline=2、quiet=7，不能出现原设计稿那种「1 moved · 9 online」合计对不上。
  - 依赖类型：功能前置 Task 7.1（`fall_event`、`collector_status`）、Task 8.2（范围校验）。`lutetia/web/api.py` 由本 Task 独占修改。
  - 证据产生者：HIGH 档（公开契约）：implementer → code-reviewer 全三 Stage → tester。
- **Task 8.4：OpenAPI 契约与契约测试（SC-14，DFX 第 9、10 维）** — 新建 `lutetia/web/openapi.json`（OpenAPI 3.1，列出 Task 8.3 全部资源、参数、信封、错误形状、两种认证方式），由 `GET /api/v1/openapi.json` 返回（需认证）；新建 `tests/test_api_v1_contract.py`（`# risk: high`）：遍历 openapi.json 里每个 GET，在合成库上调用并用 jsonschema 校验响应；另一条用例比对「openapi.json 里的资源集合」与「应用实际注册的 `/api/v1` GET 路由」完全一致（加了路由没写契约就红）。dev 依赖加 `jsonschema`（安装时取最新版，写进技术栈表）。验证：`.venv/bin/pytest tests/test_api_v1_contract.py -q`。
  - Business Context：外部调用方一旦接上，改坏字段的代价落在别人身上（Architecture §10、§11 第三条风险）；v1 只增不改要有机器守。例子：有人把 `fall-events` 的 `flips` 改名成 `flip_count`——契约测试必须红。
  - 依赖类型：功能前置 Task 8.3。
  - 证据产生者：MEDIUM 档：implementer → code-reviewer Stage 0 + 1；契约测试本身进发版测试卡点。

**验收标准**：
- 全量回归绿；新用例全绿；DB 用例 skip = 0。
- 旧 `API_KEY` 调原四个接口响应与改造前一致。
- 会话与 key 两种方式拿到的挪动事件数一致；越权 403、超限 429 实测。
- 每个 `/api/v1` 列表本机服务端 ≤ 300 ms。
- 日志不含坐标（DFX 场景 P-1）：跑完新用例后对测试日志与本机 compose 近 1 小时 `docker compose logs` 用 `grep -E '[0-9]{1,2}\.[0-9]{4,},\s*-?[0-9]{1,3}\.[0-9]{4,}'` 无输出。

---

## Phase 9: 项目看板骨架、登录、Overview 与 Manholes（SCOPE-14、18，SCREEN-1、2、5，FLOW-4，SC-10 防盗部分） ✅

本机完成（2026-11-10，CONCERNS：残留 #111）：Task 9.1 ～ 9.3 提交；CSP 假设成立（fra 实测严格 CSP 下 ECharts / Leaflet 违规 0）；fra 隔离栈 Playwright 两条走查通过、1440 首屏、ui-audit 1440 / 390 溢出 0 对比度 0；带库全量 886 passed / 1 failed（#70）。上线随下一次发版。

**交付内容**：
- 项目方在 `https://iot.digifiber.net/app/` 登录后看到 Overview：防盗状态带（24 h 挪动 / 离线 / 在线安静）、最新三条挪动事件、井盖地图，以及铜缆捆与拆除计划各一行概况；每 60 秒局部刷新。
- Manholes 页：地图 + 挪动事件时间线（24 h / 7 d / 30 d），点事件或地图标记在本页打开井盖详情抽屉（电压、信号、7 / 30 天曲线、该井盖的事件），Esc 关闭后焦点回到原处。
- 深色 / 浅色 / 投影三种主题，EN / FR 跟随浏览器且可切换；离线、数据滞后（心跳 > 90 s）、错误三种提示条按严重度只显示一条。
- 新事件到达时该标记脉冲三次，reduced-motion 下不脉冲。

**验证的假设**：
- vue-echarts 8 在严格 CSP（`style-src 'self'`）下能画图（Architecture §11 风险，技术未知）——Task 9.1 原型在 fra 用 Playwright 打开，控制台无 CSP 违规且曲线有像素即成立；不成立按 Architecture 预案改用 ECharts 直接挂载，不放宽 CSP。
- `[默认]` 首批三账号都看全部数据——Orange 账号登录后与 admin 看到的数字相同。

**关键文件**：
- `web-ui/package.json`、`web-ui/package-lock.json`、`web-ui/vite.config.ts`、`web-ui/index.html` — 前端工程（Task 9.1 唯一 owner）
- `web-ui/src/main.ts`、`web-ui/src/router.ts`、`web-ui/src/api.ts` — 入口、路由、只读 API 客户端
- `web-ui/src/styles/tokens.css` — 从 DESIGN.md 落的颜色、字号、圆角、间距 token
- `web-ui/src/i18n/en.ts`、`web-ui/src/i18n/fr.ts` — 两份字典
- `web-ui/src/components/` — StatusStrip、ManholeMap、EventRow、RangeSwitch、ManholeDrawer、Banner
- `web-ui/src/pages/Overview.vue`、`Manholes.vue`、`SignIn.vue`
- `Dockerfile` — 多阶段：node:24-slim 构建 → 产物拷进 python:3.12-slim
- `lutetia/web/app.py` — 托管 `/app/`、前端路由回退、按路径的 CSP 与安全头

**Task 清单**：
- **Task 9.1：前端工程与 CSP 原型（先验技术未知）** — 新建 `web-ui/`：Vite 8.x（2026-11-10 实装 8.3.7）、Vue 3.5.x、vue-router 5.x、vue-echarts 8.x + ECharts 6.1.x、Leaflet 1.9.4、vite-plugin-pwa ≥ 1.3（本 Phase 只装不启用），版本在 `package.json` 锁精确值；IBM Plex Sans / Mono 字体文件随构建产物自托管（与设计稿同字形）；一个占位页面画一张 ECharts 折线。`Dockerfile` 改多阶段，运行镜像不含 Node 与 node_modules。`lutetia/web/app.py`：`/app/` 托管 `web-ui/dist`，非文件路径回退 `index.html`；`/app/*` 的 CSP `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://mt0.google.com https://mt1.google.com https://mt2.google.com https://mt3.google.com; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'`（2026-11-10 按实际瓦片源改：测试阶段直拉 Google 瓦片，progress Decisions 2026-11-07；Task 13.2 收口时换回 OSM 或官方 API 再改这一行），并带 `X-Frame-Options: DENY`；ECharts 提示框一律 `renderMode: 'richText'`（默认 HTML 提示框写 `style=""` 会被严格 CSP 拦）。验证：`cd web-ui && npm ci && npm run build`；`npm audit --audit-level=critical` 无输出；`docker build .` 成功且 `docker run --rm <img> sh -c 'command -v node || echo no-node'` 打印 no-node；fra 上 Playwright 打开 `/app/` 收集 `securitypolicyviolation` 事件为 0、canvas 非空。
  - Business Context：ADR-2 选 Vue 单页应用的前提之一是严格 CSP 能守住（THR-7 跨站脚本）；这条不先验，后面所有图表页都可能返工。例子：控制台出现「Refused to apply inline style」即不成立，按预案换写法，而不是给 CSP 加 `'unsafe-inline'`。
  - 依赖类型：功能前置无；验证前置：fra 的 `~/tools/pw`。
  - 证据产生者：HIGH 档（新依赖 + 安全头 + 构建链）：implementer → code-reviewer 全三 Stage；Playwright 检查由 tester 在 fra 上跑并贴原始输出。
- **Task 9.2：token、外壳、主题、语言与登录页（SCREEN-5）** — `web-ui/src/styles/tokens.css` 按 DESIGN.md 前言逐个落 CSS 变量（深色与浅色两套，投影 = 浅色加大字号档），组件里不许出现 token 之外的十六进制颜色；外壳：顶栏（项目名、四个标签、As of、主题、EN / FR、账号菜单含 Sign out），手机宽度下改底部标签栏；`web-ui/src/i18n/` 两份字典（键与设计稿 demo/index.html 的 `T` 字典一致），首次按 `navigator.language` 选 fr 或 en；`SignIn.vue` 表单 POST 到 `/login`（带 `remember` 与 `next=/app/`），密码错显示「Wrong username or password.」；`api.ts` 遇 401 跳登录页。验证：`npm run build && npm run lint`；`node scripts/check-tokens.mjs`（新建：扫 `web-ui/src` 里的 `#rrggbb`，不在 DESIGN.md 颜色表里的即失败）；fra 上 Playwright：未登录访问 `/app/` 落到登录页，orange 登录后进 Overview，切 FR 后标签为 Vue d’ensemble / Regards / Tourets / Plan。
  - Business Context：Design-Brief §6.1 界面只用英、法，默认跟随浏览器；DESIGN.md 是颜色唯一来源。例子：法国同事浏览器是 fr-FR，第一次打开就是法语；手动切到 EN 后刷新仍是 EN（记在 localStorage）。
  - 依赖类型：功能前置 Task 9.1、Task 8.1（三账号与 remember）。
  - 证据产生者：MEDIUM 档：implementer → code-reviewer Stage 0 + 1。
- **Task 9.3：Overview 与 Manholes 页（SCREEN-1、2，CMP-1、3、4、5、6、12）** — 按设计稿 demo/index.html 的布局与状态实现：StatusStrip 读 `/api/v1/summary`（三项互斥计数，点任一项跳 Manholes 并按状态筛选）；EventRow 显示 IMEI、开始时间（Europe/Paris，标时区）、持续、翻转次数、「Notified —」占位；ManholeMap 用 Leaflet，标记形状 + 颜色双编码（安静实心圆、动过琥珀三角、正在挪动红三角、离线空心斜线圆），每个标记带「unverified」角标；ManholeDrawer 用原生 `<dialog>`，电压 / 信号曲线读 `/api/v1/manholes/{device_id}/series?days=7|30`（7 d 原始、30 d 服务端小时均值；2026-11-10 新增资源，legacy `/api/v1/telemetry` 不动，见 progress Decisions），关闭后焦点回到触发元素；Banner 按「错误 > 数据滞后 > 离线」只显示一条，数据滞后读 `/api/v1/summary` 的 `collector`（项目账号没有 status:read，2026-11-10 改）；全部安静时状态带换成「All 12 manholes quiet since …」；60 秒自动刷新，新事件到达时对应标记加 `.pulse`（600 ms × 3），`prefers-reduced-motion: reduce` 下不加。验证：`npm run build`；fra 上 Playwright 走查脚本（沿用 design-maker 的 walk.cjs 写法，新建 `web-ui/e2e/walk-manholes.cjs`）：点最新一条事件 → 抽屉打开且含该 IMEI 与「Location unverified」→ Esc 关闭、焦点回到该事件条；断开 API（拦截请求返回 503）→ 出现红色错误条且旧数据保留；reduced-motion 下 `.pulse` 动画名为 none；控制台错误 0、CSP 违规 0。
  - Business Context：FLOW-4——Orange 的项目经理周一早上打开，先看出哪口井盖被动过并点进去（防盗优先，Spec v1.13）。例子：周日 02:14 井盖 …0107 被动过 6 分钟、翻转 9 次——周一 08:42 打开 Overview，第一屏琥珀三角与事件条都指向它，点一下抽屉里能看到它 7 天电压曲线与这次事件。
  - 依赖类型：功能前置 Task 8.3（资源）、Task 9.2（外壳）。
  - 证据产生者：MEDIUM 档：implementer → code-reviewer Stage 0 + 1；Playwright 走查由 tester 在 fra 上跑。

**验收标准**：
- `npm run build`、token 检查、Python 全量回归都绿；运行镜像不含 Node。
- fra 上 Playwright：两条走查通过、控制台错误 0、CSP 违规 0、UI 审计（`.claude/scripts/ui-audit.mjs`，拷到 `~/tools/pw` 跑）溢出 0、对比度不足 0，1440 与 390 两个宽度。
- 1440 px 宽首屏不滚动看到防盗状态带、最新事件与地图（SC-10 防盗部分）。

---

## Phase 10: Bundles 与 Plan 页、CSV 导出、SLA 参考（SCOPE-14、16，SCREEN-3、4，SC-10 其余部分） ✅

本机完成（2026-11-10，CONCERNS：#112、#113）：Task 10.1 ～ 10.3 提交；Spec v1.17（段级筛选只算命中段、FR CSV 分号、去 OCC 时间轴）；fra 隔离栈 Playwright walk-bundles 三场景、walk-plan 15 步全过，ui-audit 溢出 0 对比度 0；带库全量 950 passed / 1 failed（#70）。真 SLA 表导入与「生产快照图注覆盖数」核对随下一次发版由 deployer 在 fra 做。

**交付内容**：
- Bundles 页：每台铜缆捆追踪器的最后位置与 7 天轨迹，顶部写明「只显示位置与轨迹，运输状态尚未计算」；生产当前没有上报时显示空态而不是 0。
- Plan 页：六个筛选、按分包商与按电缆型号两张计划吨数条形图（只算有明细的工单，图注写明覆盖几单）、工单表可展开电缆段、「Export filtered rows (CSV)」真下载、无重量的工单显示「weight pending」不显示 0、OCC 原文旁「Open in Ariane」。
- 运维在 fra 用 `lutetia import sla` 把三份 DEPOSE 模板导进库，Plan 页按类别显示对应 SLA 流程参考图，标「Reference only — not tracked per work order」。

**验证的假设**：
- `[推断]` Bundles 页按设备而不是按铜缆捆组织（设备与铜缆捆的对应没有台账，Architecture §9）——页面只说「tracker」，不编铜缆捆编号；用户看后挑错。
- SC-10「不开 Excel 回答计划拆多少吨、分到哪几家」——用生产快照数据在 Plan 页筛一个分包商，表内吨数合计与图上该分包商的条长一致。

**关键文件**：
- `web-ui/src/pages/Bundles.vue`、`web-ui/src/pages/Plan.vue`
- `web-ui/src/components/DeviceList.vue`、`FilterBar.vue`、`DataTable.vue`、`SourceNote.vue`、`SlaReference.vue`
- `lutetia/sla_import.py` — 新建：读三份 DEPOSE xlsx 的节点、责任方、时长（复用 `xlsx_min.py`）
- `lutetia/sql/006_sla_template.sql` — 新表 `sla_template_step`（Task 10.3 唯一 owner）
- `lutetia/cli.py`、`lutetia/import_cmd.py` — `lutetia import sla <文件>…`
- `lutetia/web/api_v1/resources.py` — 加 `/api/v1/sla-templates`

**Task 清单**：
- **Task 10.1：Bundles 页（SCREEN-3，CMP-3、7）** — `Bundles.vue`：左地图右设备列表（手机上下排），列表每行 IMEI、最后位置时间、在线状态；点设备在地图上画 7 天轨迹（`/api/v1/bundles/{id}/track?days=7`）；全部设备 24 h 无上报时显示「No position reported in the last 24 h」与最后一次上报时间；顶部固定说明一句「Shows last position and 7-day track only; trip status is not computed yet」。验证：`npm run build`；fra 上 Playwright 用合成数据（本机 compose 合成库）点一台设备后轨迹折线出现，空库时出现空态文案。
  - Business Context：铜缆捆约 250 kg 一捆，从站点运到仓库，运输途中也可能被偷（Spec v1.13 产品概述）；运输异常规则还没定（#96），本版只给位置与轨迹。例子：4072400634 最后上报 10 月 14 日——页面显示该时间与灰色离线，不显示「在途」或「已到仓」。
  - 依赖类型：功能前置 Task 8.3、Task 9.3（地图组件）。
  - 证据产生者：LOW 档：implementer 自检，主 Agent 对 diff 与 Playwright 输出验收。
- **Task 10.2：Plan 页筛选、图、表、导出（SCREEN-4，CMP-8、9、10）** — `Plan.vue` 读 `/api/v1/pois`（筛选参数随 URL 查询串保留）与 `/api/v1/pois/{poi_no}/segments`（展开时取）；两张 ECharts 横向条形图；DataTable 用真 `<table>`，展开行 `aria-expanded`；导出在浏览器里用当前筛选结果生成 CSV（UTF-8 带 BOM、逗号分隔、字段按 RFC 4180 转义），文件名 `lutetia-plan-<日期>.csv`；SourceNote 写「Excel snapshot, as of <导入时间> · Ariane is the source of truth」（as_of 取资源返回值）；筛选无结果显示「No work order matches these filters.」与「Clear filters」。验证：`npm run build && npm run test`（vitest 单测 CSV 转义：含逗号、引号、换行的分包商名导出后再解析得到原值）；fra 上 Playwright：选一个分包商后表行数 = 下载 CSV 数据行数。
  - Business Context：项目方不开 Excel 就回答计划拆多少吨、分给谁（SC-10）；没有计划重量的段不参与吨数（Spec 规则与例外「只有有电缆明细的工单才有计划吨数」）。例子：117 单里只有 25 单有明细——图注必须写「covers 25 of 117 work orders」，无明细的 92 单表里显示「weight pending」。
  - 依赖类型：功能前置 Task 8.3、Task 9.2。
  - 证据产生者：MEDIUM 档：implementer → code-reviewer Stage 0 + 1。
- **Task 10.3：SLA 模板导入与参考图（Spec 功能需求「SLA 流程参考」，OUT-9 不算超时）** — 新建 `lutetia/sql/006_sla_template.sql`：表 `sla_template_step(template text, seq int, step text, owner text, sla_text text, primary key (template, seq))`；新建 `lutetia/sla_import.py`：读 DEPOSE-Transportation / Distribution / MASSIVE 三份 xlsx 的节点顺序、节点名、责任方（客户 / 华为 / 合作方）、SLA 时长原文，整模板替换写入（单事务）；`lutetia import sla FILE [FILE…] [--dry-run]` 打印每个模板几步，日志不打单元格内容；`/api/v1/sla-templates`（`poi:read`）；`SlaReference.vue` 按工单类别（Transport → Transportation、Distribution → Distribution）显示对应模板的节点流程，MASSIVE 只在参考里列出。验证：`.venv/bin/pytest tests/test_sla_import.py -q`（新建 `# risk: medium`，用 `tests/xlsx_builder.py` 构造合成模板，覆盖重复导入不变、表头缺列报错）；契约测试自动覆盖新资源。
  - Business Context：SLA 表只能在 fra 与自己的库里（Spec 规则与例外），所以参考图不能写死进前端代码。例子：真表在 fra 的 data/poi/，导入命令只在 fra 上跑；Git 里只有合成测试表。
  - 依赖类型：功能前置 Task 8.4（契约测试要覆盖新资源）；验证前置：真表导入由 deployer 在 fra 执行。
  - 证据产生者：MEDIUM 档（迁移 + 解析器）：implementer → code-reviewer Stage 0 + 1；按 red-locks-the-bug 规则这是新解析器不是缺陷修复，不开红锁。

**验收标准**：
- Python 全量回归、`npm run build`、`npm run test` 绿。
- fra 上 Playwright：Plan 筛选与导出行数一致，Bundles 轨迹与空态都出现；UI 审计溢出 0、对比度不足 0。
- 生产快照上 Plan 页图注覆盖数 = `/api/v1/summary` 里有计划重量的工单数（`count − without_weight`；2026-11-10 由「有明细」改为「有计划重量」，有段无重量的工单不算覆盖，Task 10.2 审查 L-3）。

---

## Phase 11: 手机网页如同 App——PWA、离线上次数据、底部标签栏（SCOPE-15，SC-11） ✅

本机完成（2026-11-10，CONCERNS：#114；iPhone 实机未验证，见 #112）：Task 11.1、11.2 提交；fra 隔离栈 walk-offline 全步 PASS、退出后 Cache Storage 为空（验证假设成立）、375 四页无横向滚动、ui-audit 24 组合溢出 0 对比度 0；带库全量 953 passed / 1 failed（#70）。

**交付内容**：
- iPhone 上「添加到主屏幕」后点图标全屏打开，有应用名、图标与启动画面。
- 没网时打开显示上次数据与「Offline · data as of HH:MM」，不是白屏；退出登录清空离线缓存。
- 375 px 宽无横向滚动，触控目标 ≥ 44 px，抽屉在手机上改为全屏底部弹层。

**验证的假设**：
- `[默认]` 离线缓存只存应用外壳与每个 API 资源最近一次响应（SC-11 约束「不长期保存超过最近一次的数据」，DFX 隐私维）——退出登录后 Cache Storage 为空即成立。
- iOS Safari 对 Service Worker 与 standalone 显示的支持（技术未知）——需要用户用自己的 iPhone 实测一次，Playwright 的 WebKit 只能代替一部分；实机未测时验收写「未验证：iPhone 实机」。

**关键文件**：
- `web-ui/vite.config.ts` — 启用 vite-plugin-pwa（manifest、Workbox 运行时缓存规则）
- `web-ui/public/icons/` — 应用图标与 apple-touch-icon
- `web-ui/src/offline.ts` — 读缓存时间、退出时清缓存
- `web-ui/src/pages/*.vue`、`web-ui/src/components/ManholeDrawer.vue` — 手机布局

**Task 清单**：
- **Task 11.1：manifest、Service Worker 与退出清缓存** — `vite.config.ts` 启用 vite-plugin-pwa：`display: standalone`、名称「Ariane · Copper Watch」、图标 192 / 512 与 `apple-touch-icon`；运行时缓存只对 `/api/v1/*` 用 NetworkFirst、每个 URL 只留最新一份（`maxEntries` 按资源数设、`maxAgeSeconds` 7 天）、`/embed/` 下不注册 Service Worker；`offline.ts`：响应来自缓存时 Banner 显示离线与缓存时间；Sign out 时 `caches.keys()` 全删并注销登录。验证：`npm run build` 产物含 `manifest.webmanifest` 与 `sw.js`；fra 上 Playwright：登录 → 加载 Overview → `context.setOffline(true)` 后刷新仍显示数据与离线条 → 恢复网络后 Sign out → `caches.keys()` 返回空数组。
  - Business Context：项目方在手机上当 App 用，地铁里没信号也要看到上次数据（SC-11）；GPS 位置是防盗对象的位置，退出后手机上不留（DFX 隐私维）。例子：08:42 看过一次，09:10 在地铁里打开，显示 08:42 的数据与「Offline · data as of 08:42」；Sign out 后同一台手机离线打开只看到登录页。
  - 依赖类型：功能前置 Phase 9、10 的页面。
  - 证据产生者：MEDIUM 档：implementer → code-reviewer Stage 0 + 1；Playwright 由 tester 跑。
- **Task 11.2：手机布局与触控（SCREEN-1 ～ 4 响应式）** — 按 Design-Brief 各页「响应式」一节与设计稿 390 px 截图：底部标签栏、Manholes 地图上半屏事件列表下半屏、抽屉改全屏底部弹层、Plan 表改每单一张紧凑行、所有可点元素 ≥ 44 × 44 px。验证：fra 上 UI 审计 `--widths 375,390,1440 --themes light,dark --strict` 溢出 0、折行只允许导航标签误报；Playwright 在 375 px 宽度遍历四页 `document.documentElement.scrollWidth <= 375`。
  - Business Context：SC-11「375 px 宽无横向滚动、触控目标 ≥ 44 px」。例子：Plan 页在 375 px 宽时不能出现需要横向拖动的表格。
  - 依赖类型：功能前置 Task 11.1 无（可并行），共享文件 `web-ui/src/pages/*.vue` 本 Phase 由 Task 11.2 独占。
  - 证据产生者：LOW 档：implementer 自检，主 Agent 读审计 JSON 验收。

**验收标准**：
- 构建产物含 manifest 与 Service Worker；离线刷新显示上次数据；退出后缓存为空。
- 375 px 四页无横向滚动、UI 审计对比度不足 0。
- 用户 iPhone 实机「添加到主屏幕」一次（用户做，主 Agent 记结果；未做则写「未验证」）。

---

## Phase 12: 嵌入部件 `/embed/*`（SCOPE-20，SCREEN-E1 ～ E3，SC-15，THR-2、3、4） ✅

本机完成（2026-11-10，CONCERNS：#115）：12.1、12.2 提交；同站 iframe 带会话 cookie 假设在 fra 实测成立（ADR-6）；框入来源改由 EMBED_FRAME_ANCESTORS 单独配置（取代下文「取调用方登记 origins 的并集」，见 progress Decisions）；带库全量 977 passed / 1 failed（#70）。

**交付内容**：
- digifiber.net 下的页面用 iframe 框入 `/embed/fall-timeline`、`/embed/manhole-map`、`/embed/security-summary`：用户已登录 Lutetia 时直接显示，未登录显示「Sign in to Lutetia to see this.」并给新窗口登录链接，部件里不收密码。
- 只有 `/embed/*` 允许被 `https://*.digifiber.net` 框入，其余页面仍禁止被框入。
- 点选事件时向宿主发 `{"type": "lutetia:fall-event-selected", "v": 1, "device_id": …, "started_at": …}`，内容高度变化时发 `lutetia:resize`；只向、只收白名单来源。

**验证的假设**：
- 同站会话 cookie（SameSite=Lax）在 `*.digifiber.net` 宿主的 iframe 里会被带上（技术未知，ADR-6 的前提）——fra 上用一个 `test-host.digifiber.net` 等价的本地同站页实测；若浏览器不带，回 Architecture 改嵌入认证方式（嵌入令牌扩展点），不在本 Phase 自行放宽 cookie 属性。

**关键文件**：
- `web-ui/src/embed/` — 三个部件入口与无外壳布局（复用 Phase 9 组件）
- `web-ui/src/embed/messaging.ts` — postMessage 收发与来源校验
- `lutetia/web/app.py` — `/embed/*` 托管与 `frame-ancestors` 头（只此路径放开）
- `deploy/embed-test-host.html` — 本地同站宿主测试页（只用于验证，不部署到生产）

**Task 清单**：
- **Task 12.1：部件路由与安全头（THR-2）** — `lutetia/web/app.py`：`/embed/*` 托管同一构建产物的部件入口，CSP `frame-ancestors` 取调用方登记里 origins 的并集（本版 `https://*.digifiber.net`），不发 `X-Frame-Options`；其余所有路径保持 `frame-ancestors 'none'` 与 `X-Frame-Options: DENY`；`/embed/*` 不注册 Service Worker、响应 `Cache-Control: no-store`。验证：`.venv/bin/pytest tests/test_security_headers.py -q`（新建 `# risk: high`：按路径断言 `/embed/fall-timeline` 有 `frame-ancestors https://*.digifiber.net`、`/app/`、`/dashboard/`、`/login` 有 `'none'` 与 DENY）。
  - Business Context：只允许 digifiber.net 下的系统嵌入，其余页面一律不能被框入（SC-15、DFX 场景 S-2）。例子：任意外部站点框入 `/embed/fall-timeline`，浏览器拒绝渲染；框入 `/app/` 时 Ariane 自己的页面也被拒。
  - 依赖类型：功能前置 Task 8.2（调用方 origins）。
  - 证据产生者：HIGH 档（安全头）：implementer → code-reviewer 全三 Stage → tester。
- **Task 12.2：三个部件、登录提示与 postMessage（SCREEN-E1 ～ E3，CMP-11，THR-3）** — `web-ui/src/embed/`：`FallTimeline.vue`、`ManholeMapEmbed.vue`、`SecuritySummary.vue` 复用 EventRow、ManholeMap、StatusStrip，默认浅色主题、`lang` 取查询参数缺省按浏览器、宽度跟随容器最小 280 px；`/api/v1` 返回 401 时显示 CMP-11 与 `target="_blank"` 的登录链接；`messaging.ts`：发送时 `targetOrigin` 用 `document.referrer` 的来源且必须在白名单（构建时从 `/api/v1/embed-config` 取，该资源只返回白名单模式），收到消息先校验 `event.origin`，不在白名单直接丢弃；消息只带设备号与时间，不带位置。验证：`npm run test`（vitest：非白名单 origin 的消息被丢弃、发送目标不在白名单时不发送）；fra 上 Playwright 打开 `deploy/embed-test-host.html`（经同站域名访问）：已登录时部件显示事件、点一条后宿主收到 `v: 1` 消息；清 cookie 后部件显示登录提示且页面内没有密码输入框。
  - Business Context：别的系统不用自己画井盖与挪动事件（Spec 功能需求「嵌入部件」）；部件只读、不收密码（THR-2、OUT-12）。例子：Ariane 的工地页框入时间线，项目经理点 02:14 那条，Ariane 收到 `{"type":"lutetia:fall-event-selected","v":1,"device_id":"864317087590107",…}` 自己决定跳到哪；部件自己不跳转。
  - 依赖类型：功能前置 Task 12.1、Phase 9 组件。`/api/v1/embed-config` 加在 `lutetia/web/api_v1/resources.py`，并同步 `openapi.json`。
  - 证据产生者：MEDIUM 档：implementer → code-reviewer Stage 0 + 1；Playwright 由 tester 在 fra 跑。

**验收标准**：
- 安全头测试与部件单测绿；Python 全量回归绿。
- fra 上同站宿主页实测：显示、未登录提示、消息往来三项都过；非白名单宿主框入被拒。
- 部件页面无 Service Worker 注册、无密码输入框。

---

## Phase 13: 给 Orange 看之前的收口——运维看板英法化、底图与豁免收回、残留清理（待办 #94、#88、#85）

本机代码完成（2026-11-11）：13.1、13.2、13.3 代码部分提交；OSM 假设在 fra 实测成立（68 瓦片全 200）；全量 1011 passed / 0 failed。**未完成**：#88 生产收回（用户换强密码、删 DASHBOARD_LOGIN_LOCKOUT=off，发版后主 Agent 实测锁定），按验收标准「#88 三项全部关闭后才算本 Phase 完成」，本 Phase 暂不标 ✅。

**交付内容**：
- 运维看板 `/dashboard` 所有界面文字改英 / 法、跟随浏览器，不再出现中文。
- 地图底图从测试阶段的 Google 瓦片换回 OpenStreetMap（修 referrerPolicy），页面保留署名；两个看板与部件一致。
- 用户换强密码、删掉 `DASHBOARD_LOGIN_LOCKOUT=off` 后，登录锁定实测生效（#88）；Task 5.3 复核的三条 Low 修掉（#85）。

**验证的假设**：
- OSM 标准瓦片在加了正确 `referrerPolicy` 后能正常加载（2026-11-07 改 Google 瓦片的原因）——fra 上 Playwright 打开地图页，瓦片请求 200 且无 403；不成立则改用 Google 官方 Maps JavaScript API 的方案回 Spec 定（涉及密钥与费用，用户拍板）。

**关键文件**：
- `lutetia/web/i18n.py` — 新建：运维看板英、法字典与 Accept-Language 选择
- `lutetia/web/html.py`、`lutetia/web/dashboard.py`、`lutetia/web/pages_device.py`、`lutetia/web/pages_map.py`、`lutetia/web/static/*.js` — 文字走字典
- `lutetia/web/static/map.js`、`web-ui/src/components/ManholeMap.vue` — 底图来源
- `lutetia/import_cmd.py` — #85 三条 Low

**Task 清单**：
- **Task 13.1：运维看板英 / 法（#94）** — 新建 `lutetia/web/i18n.py`（两份字典 + 按 `Accept-Language` 选 fr 或 en，可用 `?lang=` 覆盖并记 cookie）；服务端模板与静态 JS 里的中文文案全部换成字典键。验证：`.venv/bin/pytest tests/test_dashboard.py tests/test_i18n.py -q`（`test_i18n.py` 新建 `# risk: low`）；`grep -rnP '[\x{4e00}-\x{9fff}]' lutetia/web --include=*.py --include=*.js --include=*.html` 无输出。
  - Business Context：界面只用英文与法语，所有界面包括运维看板（Spec v1.13 决策依据「界面语言」）。例子：法语浏览器打开运维看板首页，异常块标题是法语。
  - 依赖类型：功能前置无。
  - 证据产生者：LOW 档（文案，< 50 行逻辑）：implementer 自检，主 Agent 对 diff 与 grep 输出验收。
- **Task 13.2：底图换回 OSM（#88 第三项）** — 运维看板 `map.js` 与项目看板 `ManholeMap.vue` 的瓦片地址改为 `https://tile.openstreetmap.org/{z}/{x}/{y}.png`，`<img>` 的 `referrerPolicy` 设为 `strict-origin-when-cross-origin`，署名「© OpenStreetMap contributors」；CSP `img-src` 同步去掉 Google 域。验证：fra 上 Playwright 打开 `/dashboard/map` 与 `/app/#/manholes`，统计瓦片响应状态全部 200。
  - Business Context：测试阶段直拉 Google 瓦片是已接受的临时豁免，给 Orange 看之前收回（progress Decisions 2026-11-07、待办 #88）。例子：上线后地图右下角显示 OSM 署名，网络面板里没有 google 域请求。
  - 依赖类型：功能前置 Task 9.3。
  - 证据产生者：LOW 档：implementer 自检，主 Agent 读 Playwright 输出验收。
- **Task 13.3：#85 三条 Low 与豁免收回核查** — `lutetia/import_cmd.py` 连库异常捕获补 `ValueError`（L-A）及 #85 记的另两条；用户在 fra 换强密码并删掉 `DASHBOARD_LOGIN_LOCKOUT=off` 后（用户亲手改环境文件），主 Agent 实测同一 IP 连续 5 次错密码后第 6 次 429。验证：`.venv/bin/pytest tests/test_cli_import.py -q`；生产实测的 curl 输出贴进验收记录（不贴密码）。
  - Business Context：测试阶段弱口令与关锁定是用户接受的风险，期限到给 Orange 看为止（THR-9）。例子：收回后用 123456 登录失败、5 次后被锁 5 分钟。
  - 依赖类型：验证前置——用户改环境文件。
  - 证据产生者：LOW 档：implementer 自检；生产实测由主 Agent 亲跑。

**验收标准**：
- 全量回归绿；`lutetia/web` 下中文 0 处。
- 两个看板地图走 OSM、无 Google 请求。
- 生产登录锁定生效；待办 #88 三项全部关闭后才算本 Phase 完成。

---

## 范围外（本次不计划）

- OUT-14 Lutetia 与 Ariane 的具体对接（登记 Ariane 为调用方、Ariane 用哪些资源、POI 来源切到 Ariane）：已押后——用户 2026-11-08「下一步开发，具体开发要 Ariane 自己去开发」；本迭代只把契约与登记机制做好，对接开始时回本计划开 Task（只加登记与来源适配，不改契约）。
- 主动通知（#95）、铜缆捆运输异常（#96）、井盖实时位置（#97）：待确认——分别等用户单独谈、项目清晰、Dingtek 厂家答复；页面已留「Notified —」与「trip status is not computed yet」的位置。
- OUT-13 外部域名嵌入（嵌入令牌）、webhook 推送、写入型接口：已押后——出现第一个外部域名嵌入方或第一个要推送的调用方时回 Architecture §5 扩展点。
- GPS 位置保留期与告知义务（#93）：待确认——项目合规负责人答复前按 high 档保护、不删数据，不排 Task。
- 运维看板 `/dashboard/data` 迁入 `/api/v1`：已押后——Architecture §9，运维看板大改时再迁。
- GPS51 转发打通（#31，Phase 3 剩余）：外部条件，不在本迭代；打通后补 Phase 3 的 SC-3 / SC-4 生产证据。

---

## 技术栈

沿用首版，Python 侧不引新依赖、不升级；v1.4 起前端静态库随包自托管（见下表）。版本为 2026-11-06 本机 venv 实装与 Spec 技术方向表记录的 PyPI 核对结果。

| 层级 | 技术 | 版本 | 说明 |
|------|------|------|------|
| 语言 | Python | 代码按 3.9 写法；本机 venv 3.14.4；容器 python:3.12-slim | 目标机版本未定（待定 3），Task 1.2 机器检查 3.9 写法 |
| HTTP / WebSocket | aiohttp | ≥ 3.9（本机 3.14.5） | 客户端 + 推送接收端 + Dingtek WebSocket；3.9 目标机会退到最后支持 3.9 的 3.1x |
| 数据库驱动 | asyncpg | ≥ 0.29（本机 0.32.0） | unnest 批量 upsert |
| 测试 | pytest / pytest-asyncio | ≥ 7（本机 9.2.0）/ ≥ 0.21（本机 1.4.1） | asyncio_mode=auto；DB 用例连不上库自动 skip |
| 数据库 | PostgreSQL | 16（postgres:16-alpine） | 本机 lutetia-pg 容器 127.0.0.1:15433；生产 compose 内网 db:5432 |
| 部署 | Docker Compose | v2（本机 2.40.3） | migrate → run；状态目录与数据各一卷 |
| 包管理 | pip + venv | — | `pip install -e ".[dev]"`；内网侧装包加 `-i https://mirrors.aliyun.com/pypi/simple` |
| 前端静态库（v1.4） | Chart.js / Leaflet | 4.6.1（MIT）/ 1.9.4（BSD-2-Clause） | 2026-11-06 向 npm 仓库核过版本与许可证；从 jsdelivr 按精确版本下载进 `lutetia/web/static/vendor/` 随包发布，不走 CDN；地图底图 OpenStreetMap 标准瓦片（浏览器直连，页面保留署名） |
| xlsx 读取（Phase 5） | Python 标准库 zipfile + xml.etree.ElementTree | 随 Python | 不引 openpyxl：台账只要读单个工作表的值，标准库够用，镜像与依赖不变；解压上限 50 MB 防压缩炸弹 |
| 反向代理 / 证书（v1.3） | nginx / certbot | 1.24（主机自带）/ 2.9 | 主机 nginx server block + Let's Encrypt，`deploy/host-deploy.sh` 幂等部署 |
| 前端构建（Phase 9 起） | Node.js / Vite | 24 LTS（node:24-slim，只在构建阶段）/ 8.0.x | Architecture-Design 2026-11-08 联网核过；运行镜像不含 Node |
| 前端框架（Phase 9 起） | Vue / vue-router | 3.5.x（3.6 仍 beta 不用）/ 5.x | vue-router 5.1.0 于 2026-06 发布、5.0 声明无破坏性改动；安装时核 peerDependencies |
| 图表 / 地图（Phase 9 起） | ECharts + vue-echarts / Leaflet | 6.1.x + 8.x / 1.9.4 | vue-echarts 严格 CSP 风险由 Task 9.1 先验 |
| PWA（Phase 11） | vite-plugin-pwa | ≥ 1.3.0（1.2 不支持 Vite 8） | manifest + Workbox 运行时缓存 |
| 前端单测 | vitest | 安装时取最新正式版 | 只测 CSV 转义、postMessage 来源校验这类纯逻辑 |
| 契约测试（Phase 8） | jsonschema（dev 依赖） | 实装 4.26.0，下限 4.25 以兼容 3.9 | 用 openapi.json 校验 `/api/v1` 响应；不进运行镜像 |
| 备份上传（Phase 6） | 腾讯云 coscli | 安装时取最新正式版，装在 fra 宿主机 | COS 官方称 S3 兼容但不保证完全一致，「只写不删」由 Task 6.3 实测 |
| 浏览器验证 | Playwright + Chromium | fra `~/tools/pw` 现有 | 本机没有 playwright；UI 审计与走查都在 fra 跑 |

## 数据库表

五张表两个视图全部在首版 `sql/001_schema.sql` 建好；Phase 1 ～ 4 不加表、不改列，Phase 5 新增 `poi` 与 `poi_cable_segment` 两张表（`sql/003_poi.sql`），不碰现有表。

| 表名 | 所属 Phase | 用途 |
|------|-----------|------|
| `device` | 首版（已建） | 两源设备，(source, device_id) 主键，expected_online 标应在线 |
| `gps_position` | 首版（已建） | GPS 位置宽表，(device_id, update_time) 去重，raw 存原始 JSON |
| `sensor_telemetry` | 首版（已建） | Dingtek 遥测窄表，(device_id, key, ts) 去重 |
| `sensor_attribute` | 首版（已建） | Dingtek 属性，整表覆盖，status 读 uploadInterval |
| `api_call` | 首版（已建） | 每次外部调用一行，配额守护与 status 统计读它 |
| `gps_position_v` / `sensor_telemetry_v` | 首版（已建） | 换算视图，volt ÷100、rsrp ÷10 为 `[默认]` |
| `poi` | Phase 5 | POI 工单（台账一单一行），poi_no 主键，content_sha 判新增 / 更新 / 未变，in_ledger 标台账里还有没有 |
| `poi_cable_segment` | Phase 5 | 工单下的电缆段，(poi_no, seq) 主键，计划重量与参考重量；没有电缆明细的工单没有段 |
| `backup_run` | Phase 6 | 每次备份一行：时间、成败、对象键、大小、sha256、各表行数（恢复演练拿它核对） |
| `collector_status` | Phase 7 | 采集心跳，只有一行（id = 1），每 30 秒覆盖；web 只读 |
| `fall_event`（视图） | Phase 7 | alarmFall 翻转按 30 分钟窗口合并的挪动事件，现算不落表（ADR-3） |
| 角色 `lutetia_ro` | Phase 7 | web 容器连库用的只读角色，GRANT SELECT 与默认权限 |
| `sla_template_step` | Phase 10 | 三套 DEPOSE SLA 模板的节点、责任方、时长原文，只作参考图 |

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
