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

## Phase 1: 首版对账——对照 Spec 审查、兼容与密钥闸、推送接收端实测

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
- `lutetia run` 在本机连续跑 2 小时：10 台在线 DC414 各有新行，最新 volt / temperature 与厂家 REST 一致，期间 Dingtek 登录 0 次（SC-2）。
- 推送静默 15 分钟后自动切轮询、碰到预算暂停 1 小时，日志与 api_call 表能对上（SC-4 本地变体，预算压到 20）。
- `lutetia status` 的失联判定有回归测试：应在线设备超时退出码 1，非在线设备不告警，uploadInterval 长的设备按 2 倍宽限（SC-5）。
- SIGTERM 后进程干净退出（任务取消、接收端关闭、连接池关闭），退出码 0。

**验证的假设**：
- WebSocket 订阅在小时级心跳的设备上稳定（Spec「Dingtek 实时订阅」条目，来源代码现状；2026-11-05 只连过约 2 分钟）——2 小时内 `dingtek ws` 日志有新行、断线有 `reconnecting` 与退避记录、没有连续失败。
- `[推断]` 失联阈值「3 小时与 2 倍 uploadInterval 取大」——Task 2.1 用例三：uploadInterval='2'（小时）、最新数据 3.5 小时前，不报 STALE；删掉 uploadInterval 行再跑，报 STALE。
- `[推断]` 日预算到顶暂停 1 小时（FLOW-2 失败路径）——本地预算压到 20，日志出现 `gps51 daily budget reached: 20/20; polling paused for 1h`，之后 1 小时 api_call 里 gps51 行数不再增长。
- 静默切换阈值 15 分钟（`[确认]`）——本机没有推送，启动后第 15 ～ 16 分钟出现 `gps51 push silent for 15 min -> polling every 60s`。

**关键文件**：
- `tests/test_status.py` — 新建：cmd_status 的失联判定与退出码回归（Task 2.1 唯一 owner）
- `lutetia/cli.py` — cmd_status 只读不改；测试若需要改它的可测性，改动归 Task 2.1 并在派单里写明

**Task 清单**：
- **Task 2.1：新建 tests/test_status.py——失联判定与退出码回归（SC-5、SCOPE-7）** — 头行 `# risk: high`；复用 tests/test_db.py 的 db fixture 写法（DATABASE_URL 不可达则 skip）；每个用例用 `"test-status-" + uuid4()` 做 device_id，结束时删掉自己插的 device / sensor_telemetry / sensor_attribute 行。用例一：source=dingtek、expected_online=true、无任何遥测 → `cmd_status(cfg, args)`（args.max_age_hours=3）返回 1，capsys 输出含 `STALE` 与 `1 expected-online device(s) without recent data`。用例二：同上但 expected_online=false → 返回 0、输出无 `STALE`。用例三：expected_online=true、sensor_attribute 里 uploadInterval='2'、最新遥测 ts 为 3.5 小时前 → 返回 0；删掉 uploadInterval 行再跑 → 返回 1。用例四：Config 的 database_url 指向 127.0.0.1:1 时 `cmd_status` 抛连接异常（FLOW-3 失败路径，不许打印「全部正常」）。验证命令：`python -m pytest -q tests/test_status.py`
  - Business Context：status 的退出码是运维唯一的告警入口（FLOW-3），错报漏报都要人跑现场。区分例子：4072407783 从未上线、expected_online=false、没数据——不许算 STALE；一台在线 DC414 5 小时没数据——必须 STALE 且退出码 1。
  - 依赖类型：功能前置 无（cmd_status 已存在）；验证前置 lutetia-pg 在线；现有库里的真实设备行不动，用例只碰自己插的行。
  - 证据产生者：MEDIUM 档（新文件约 80 行）——tester（fresh，不是首版作者）写；code-reviewer Stage 0 + 1 复核一次；主 Agent 亲跑读输出。

**验收标准**：
- `python -m pytest -q` 全绿，含 tests/test_status.py 4 条；原有用例未破坏。
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
- **Task 3.1：docker-compose 等库就绪再启动 + 部署文档补随机路径（SCOPE-10）** — 改 `docker-compose.yml`：db 服务加 `healthcheck`（`test: ["CMD-SHELL", "pg_isready -U lutetia -d lutetia"]`，interval 5s、timeout 3s、retries 10）；collector 的 `depends_on` 改为 `db: condition: service_healthy`。README 部署节第 2 步补「PUSH_PATH 建议设成 `/gps51/push/<随机 20 位>`，GPS51 后台填完整路径」；`.env.example` 的 PUSH_PATH 行上加同样一句注释。验证命令：`docker compose config >/dev/null && docker compose up -d --build && sleep 20 && docker compose ps && docker compose logs collector | grep -E 'applied 001_schema.sql|lutetia running' && curl -s localhost:8080/health; docker compose down -v`
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
