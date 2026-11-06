# Project: Lutetia 巴黎项目 IoT 数据采集服务
_Last updated: 2026-11-06_

## Pinned（仅高置信"必须遵守"写入；受保护不可修订）
- GPS51 绝不自动循环调 querytracks，连每日回补也不走它（依据：厂家明文禁止服务器自动同步轨迹，违者封 API——Spec 规则与例外、TASK.md 反直觉设计 1；适用范围：所有自动路径；人手敲 `lutetia gps51 tracks` 不在此列，每设备每天 5 次由人自己数）
- 凭据只从环境变量读；代码、日志、测试、回执里零密码零 token（依据：TASK.md Agent 约束、Spec SC-6；适用范围：全仓；本地 .env 已 gitignore 可以放，但不读它核对、不整包导出）
- 代码按 Python 3.9 写法：无 match、无 `X | Y` 类型联合、无 3.10+ 标准库（依据：目标机 Python 版本未定，TASK.md Agent 约束；适用范围：lutetia/** 与 tests/**；容器用 python:3.12-slim 不受影响）
- 调试期对真实接口有上限：GPS51 每次运行总调用 ≤ 20 次、间隔 ≥ 2 秒；Dingtek 只在 token 文件不存在时登录一次（依据：Spec 规则与例外，TASK.md Agent 约束；适用范围：本机开发与验收；生产不适用）
- .claude/ 框架脚手架目录不入库（依据：用户 2026-11-06 决定，与姊妹下游仓一致；适用范围：本仓；.gitignore 已有此条）

## Decisions（按时间顺序追加，历史不可改；三要素缺一不算决策）
- 2026-11-06: 本轮开发计划不加新功能，只把 SC-1 ～ SC-5 逐条拿到客观证据，顺手补验证中发现的缺口（依据：首版提交 9d8cc7e 已覆盖 SCOPE-1 ～ SCOPE-10 全部功能条目，但成功判据里只有 SC-6 有运行证据；适用范围：DEV-PLAN.md 本版 3 个 Phase 5 个 Task；取代：无）
- 2026-11-06: 本地任何 GPS51 运行先设 `GPS51_DAILY_BUDGET=20`，让代码自己的预算守护兜住调试期上限（依据：Spec 调试期约束每次运行 ≤ 20 次；预算按 api_call 表 24 小时内计数，跨运行累计，比按次更严；适用范围：本机开发与 Phase 1 / Phase 2 验收；生产 compose 不带这个覆盖；取代：无）
- 2026-11-06: implementer 一律 sonnet，HIGH 档也不传 opus；code-reviewer 按框架默认（依据：Spec 决策依据「解析映射与单元测试用 haiku，采集主循环用 sonnet，不用 opus」，来自 TASK.md 模型分配，用户当前指令优先于框架的 HIGH 档升 opus 规则；适用范围：本项目所有 implementer 派单；取代：无）
- 2026-11-06: Phase 3 部署默认把 PUSH_PATH 设成带随机段的路径，不做鉴权、不加 HTTPS 终结（依据：Spec 待定 4 押后期间的默认是明文 8080 不鉴权，随机路径段是零代码缓解；适用范围：到用户回答待定 4 之前；用户要共享密钥校验时回 DEV-PLAN 开 Task 改 PushReceiver._handle，现在不预开；取代：无）
- 2026-11-06: 推送写库失败策略——连接类故障（OSError、asyncio.TimeoutError、asyncpg.PostgresConnectionError、OperatorInterventionError、InsufficientResourcesError、非 ValueError 的 InterfaceError）在内存里退避 1 秒起翻倍、封顶 30 秒、无限重试直到成功；其它异常（服务端 DataError 等数据类错误、解析 bug）丢弃该 payload 并计 failed（依据：审查 H-2 发现 200 后写库失败即丢行，服务是唯一存档；F2b 发现整个 PostgresError 都重试会被一条毒行卡死队列；判定函数 `is_transient_db_error` 在 db.py；适用范围：PushReceiver._store 一条路径；落盘缓冲是下一版的事；取代：无）
- 2026-11-06: 批量写入遇非瞬时异常回退逐行插，仍失败的那一行丢弃并写 warning（带 device_id 与时间），瞬时异常整批或逐行都原样上抛让调用方重试（依据：复核 N-1——整批 INSERT 要么全成要么全败，一条 moving=70000 这类毒行会让轮询游标永不推进、每分钟烧配额且所有设备都存不进去；适用范围：db.py 的 insert_gps_positions 与 insert_telemetry 两条写入路径；取代：无）
- 2026-11-06: 停机顺序为先停收新请求、给队列最多 30 秒（drain_timeout）写完、再取消消费者；容器 stop_grace_period 要配 40 秒（依据：审查 H-3 停机直接 cancel 丢队列；复核 N-5 Docker 默认 10 秒 SIGKILL 会让清队列来不及；适用范围：PushReceiver.stop 与 docker-compose 的 collector 服务；进程被 SIGKILL 时队列里的推送仍会丢，Spec 已记为残余风险；取代：无）
- 2026-11-06: gps_position.raw 存 JSON 对象不是 JSON 字符串；sql/002_raw_jsonb_fix.sql 幂等迁移存量行，migrate 每次启动都跑（依据：审查 M-1——db.py 先 json.dumps 再经 jsonb codec 双重编码，真库 4 行 `jsonb_typeof='string'`、`raw->>'deviceid'` 为 NULL；适用范围：db.py insert_gps_positions 与 sql/ 迁移；取代：无）
- 2026-11-06: 回补单台设备失败（DingtekError、aiohttp.ClientError、超时、返回非 JSON）不中止整批，记入 last_failures 继续下一台；CLI 打印 FAILED 清单并退出码 1（依据：审查 M-6 一台出错整批中止、每日 reconcile 会被拖垮；复核 N-4 厂家维护页返回 200 + HTML 也要隔离；适用范围：DingtekSync.backfill 与 cmd_backfill；FLOW-1 第 3 步「末行 inserted rows: 0」在有失败时不再成立，Spec v1.1 已改；取代：无）
- 2026-11-06: Dingtek WebSocket 重连退避只在会话撑满 60 秒后才归零，连上就断的按 5→10→…→120 增长；拿到 token 120 秒内再被拒（errorCode=3 或握手 401 / 403）不重新登录、只按退避等待（依据：审查 M-4 服务端一连上就关时永远 5 秒且每 15 秒登录一次，违反「Dingtek 登录 24h ≤ 1」；复核 N-3 握手 401 路径同样要保护；适用范围：DingtekWs.run；取代：无）
- 2026-11-06: GPS51 登录失败按 60 秒 × 2^(n-1) 退避、封顶 1 小时，退避期内 ensure_token 不发网络请求直接抛 Gps51Error；请求超时与网络异常也记一条 ok=False 的 api_call；轮询游标在本批入库成功后才推进（依据：审查 M-2 服务先起、白名单后加那段时间会把 1400 预算全烧在 login 上；M-3 超时不计数让配额守护低估用量；H-4 游标先推进遇写库失败永久跳过那批记录；适用范围：Gps51Client.login / _post 与 Gps51Poller.poll_once；取代：无）
- 2026-11-06: git 作者身份在仓库本地配成 `zylimit <zylimitde@gmail.com>`（依据：本机没有任何 user.* 配置，首版提交 9d8cc7e 用的是 tailscale 主机名自动生成的邮箱；适用范围：本仓本机提交，不改全局配置；取代：无）
- 2026-11-06: 审查收敛——一轮只 HIGH 阻断，修完由同一轮 reviewer 复核一次即收口，Medium / Low 残留记进本文件随后续 Task 顺手修，不派 fresh reviewer 开新一轮（依据：CLAUDE.md 开发测试规则「审查收敛」；Phase 1 复核无新 HIGH 后按此收口，N-1 ～ N-6 作残留顺手修；适用范围：本项目所有 Task 的 review → fix 闭环；取代：无）

## TODO（权威待办清单）
- [P1][OPEN][#6] Phase 3 开工前用户回答待定 3（目标机 Python 版本）与待定 4（推送接收端 HTTPS / 鉴权）（Context：Product-Spec.md 待定问题表、DEV-PLAN.md 开工前置）
- [P1][OPEN][#7] Phase 2 Task 2.1（tests/test_status.py 失联判定回归）与 Phase 3 Task 3.1（compose 健康检查 + stop_grace_period 40s + 部署文档随机路径）按 DEV-PLAN.md 顺序排在 Phase 1 之后（Context：DEV-PLAN.md Phase 2 / Phase 3）
- [P0][OPEN][#8] Phase 1 收口：提交 F12 / F13 / N-3 / N-4 / N-6 修复与 Spec v1.1 / CHANGELOG / DEV-PLAN 改动，走四步走（Code Review → 测试完整性 → 编译验证 → 功能测试）并出收尾四态门结论（Context：工作树未提交改动 `git diff --stat` 8 个文件；DEV-PLAN.md Phase 1 验收标准）
- [P1][OPEN][#9] Task 2.0 把 lutetia/sources/dingtek.py（现 306 行）拆成 dingtek/ 包（client / sync / ws），`__init__` re-export，拆完 Phase 2 长跑才落在最终布局上（Context：DEV-PLAN.md Phase 2 Task 2.0；复核 Stage 2 文件规模项）
- [P1][OPEN][#10] 用户回答两条新待定问题：推送「静默」按任何合法 JSON 还是真入库的位置算（押到 Phase 2 本地长跑之前）；GPS51 报警转发消息（带 alarmtype）要不要当位置入库（押到 GPS51 后台配转发之前，建议识别后只计数不入库）（Context：Product-Spec.md v1.1 待定问题表末两行；审查反例 1、2）
- [P1][OPEN][#11] M-8：tests/test_db.py 的 GPS 幂等与属性用例会改写本地真库的 device.extra（真设备 79702a70… 被写成 `{}`）与 sensor_attribute，Phase 2 长跑前改成独立库或唯一 id 并自清理（Context：审查 Task 1.1 报告 M-8；tests/test_db.py:31、:63-66）
- [P2][OPEN][#12] N-3 / N-4 补用例：WS 握手 401 在新 token 120 秒内不 invalidate；回补单台返回非 JSON 时隔离继续（tester 未写，implementer 按规则不自写测）（Context：lutetia/sources/dingtek.py；tests/test_dingtek_ws.py、tests/test_dingtek_sync.py）
- [P2][OPEN][#13] tests/test_compat.py 的密码前缀扫描依赖 git，在无 git 环境（python:3.9-slim 容器）应明确 `pytest.skip` 并说明，而不是 FileNotFoundError（Context：tests/test_compat.py test_no_credential_prefixes_in_repo）
- [P2][OPEN][#14] M-5：GPS51 与 Dingtek 的登录失败计数只在内存，CLI 重跑之间不退避，FLOW-1 失败路径「连续失败时间隔自动拉长」跨进程不成立（Context：审查 Task 1.1 报告 M-5；lutetia/sources/gps51.py、dingtek.py）
- [P2][OPEN][#15] service.run 启动期先 await reconcile 再等 stop 事件，SIGTERM 要等 reconcile 跑完（本机实测约 20 秒）才响应，改成后台任务（Context：implementer A 的 Domain findings，scratchpad run-A.log；lutetia/service.py run）
- [P2][OPEN][#16] L-2：`lutetia gps51 sync-devices` 只同步 GPS51 设备，Spec 设备同步条目写的是两源都同步（Context：审查 Task 1.1 报告 L-2；lutetia/cli.py cmd_gps51）
- [P1][DONE][#1] Task 1.1 首版对照 Spec 审查并修 HIGH 缺陷（evidence：commit 060fd04）
- [P1][DONE][#2] Task 1.2 新建 tests/test_compat.py（evidence：commit 48f97bd）
- [P1][DONE][#3] Task 1.3 PushReceiver 补 unrecognised 计数进 /health，SC-3 本机实测（evidence：commit 060fd04）
- [P1][DONE][#4] `.serena/` 加进 .gitignore（evidence：commit 48f97bd）
- [P1][DONE][#5] Spec SC-1 基线改实数并记 CHANGELOG——已随 v1.1 修订一并改，等用户复述签字（evidence：./Product-Spec.md 成功判据表、./Product-Spec-CHANGELOG.md v1.1）

## In Progress
- 无

## Done（最近完成的放前面）
- 2026-11-06: 复核新发现 N-1（毒行卡住轮询）与 N-2（3.9 下 asyncio.TimeoutError 不是 OSError）按 red-lock 修好——tester 先写 2 条红、主 Agent 亲见整批 DataError / 0x00 失败、implementer 在 db.py 加 `_insert_skipping_poison` 逐行回退并把瞬时集合与 `is_transient_db_error` 搬到 db.py；N-3 / N-4（dingtek.py）与 N-6（断言收紧）同时修完；全量 pytest 49 passed、compileall rc=0；待提交（evidence：工作树 `git diff --stat` db.py +55 / gps51.py 9 / dingtek.py 13 / tests 两文件）
- 2026-11-06: Product-Spec 升 v1.1 + CHANGELOG v1.1 条目——SC-1 / SC-3 / SC-6 基线改实数，推送接收、回补、实时订阅、会话守护、健康端点五条功能条目按修复后行为改写，规则与例外第 3 行、FLOW-1 第 3 步、非功能「可靠」同步，决策依据加 3 行，待定问题表加 2 行；predev-lint 通过；等用户复述签字（evidence：./Product-Spec.md、./Product-Spec-CHANGELOG.md；`node .claude/scripts/predev-lint.mjs` 输出「通过（检查 1 份，warning 0）」）
- 2026-11-06: DEV-PLAN.md 加 Phase 2 Task 2.0（拆 dingtek.py）与 Task 3.1 的 stop_grace_period 40s，待提交（evidence：./DEV-PLAN.md）
- 2026-11-06: SC-1 幂等本机实测——`lutetia backfill dingtek --from 2026-08-21 --to 2026-11-05` 12 台全部 `0 new rows`、末行 `inserted rows: 0`、`0/12 devices failed`、日志无 error / login；24 小时内 Dingtek login 0（evidence：scratchpad backfill-sc1.log；api_call 表查询 timeseries 1944 / login 0）
- 2026-11-06: [#1] Task 1.1 首版对照 Spec 审查并修 HIGH——code-reviewer 全三 Stage 报 HIGH 4（H-1 JWT 进日志、H-2 写库失败丢推送、H-3 停机丢队列、H-4 游标先推进）/ Medium 8 / Low 2 / 反例 3；按 red-lock 走：tester 先写 19 条红、主 Agent 亲见失败并 touch .red-verified、两名 implementer 并行修绿（A：gps51.py；B：dingtek.py / db.py / cli.py / sql/002）、F2b 重试集合收窄补 2 条红再修、原 reviewer 同轮复核 11 条全部已修且无新 HIGH；顺手修 M-1 / M-2 / M-3 / M-4 / M-6 / M-7 / L-1 / F11（evidence：commit 060fd04；pytest 46 passed）
- 2026-11-06: [#3] Task 1.3 /health 加 unrecognised / failed，README 补字段清单；SC-3 本机四步实测：POST 位置 200 用时 10 ms、5 秒内落库且 raw 为 object、重复投递行数仍 1、`{not json` 与空体 400、`{"hello":"world"}` 200 且 unrecognised=1、/health received=3 stored=1 rejected=2 unrecognised=1 failed=0、SIGTERM 后 `shutdown requested` 退出 8080 释放（evidence：commit 060fd04；scratchpad run-A.log）
- 2026-11-06: [#2] Task 1.2 tests/test_compat.py 四条用例全绿，主 Agent 用反例验证用例一 / 二 / 三各自会红、合规写法绿；python:3.9-slim 容器真跑 `lutetia --help` 正常、解析器与兼容用例 17 passed，密码扫描条因容器无 git 报 FileNotFoundError（宿主机绿）（evidence：commit 48f97bd；`python -m pytest -q -p no:cacheprovider` 22 passed）
- 2026-11-06: [#4] `.serena/` 与 `build/`（容器 pip install 留下的 root 属主目录，已用容器 rm 清掉）加进 .gitignore（evidence：commit 48f97bd、060fd04）
- 2026-11-06: DEV-PLAN.md 生成，193 行、3 个 Phase、5 个 Task，plan-lint 通过（evidence：./DEV-PLAN.md；`bash .claude/scripts/plan-lint.sh DEV-PLAN.md Product-Spec.md` 输出「plan-lint: 通过」，Spec 无 REQ 编号故覆盖检查跳过）
- 2026-11-06: recap 完成——读 Product-Spec.md v1.0 与 CHANGELOG，核工作树干净、首版提交 9d8cc7e、pytest 18 passed（evidence：`python -m pytest -q -p no:cacheprovider` 输出 18 passed in 0.79s）

## Risks & Assumptions
- Risk：首版 1600 行从未对照 Spec 审过，而 Spec 又是从代码转写的，「代码等于 Spec」是循环论证（Mitigation：Task 1.1 派 fresh code-reviewer 独立审一遍）→ 2026-11-06 已审，HIGH 4 条修完复核通过
- Risk：上一 session 2026-11-05 的 backfill 与短暂 run 没记进任何文档，本地库状态只能靠查库反推（Mitigation：实况已记进 Context Index；Phase 1 复跑回补拿幂等证据）→ 2026-11-06 复跑已拿到 0 新增证据
- Risk：逐行回退让含毒行的批次多 N+1 次往返，Dingtek 一个窗口可能上千行，毒行出现时会明显变慢（Mitigation：毒行只在厂家下发越界值或 `\u0000` 时出现，现有样例里没见过；二分优化留给以后）
- Risk：毒行 warning 的异常文本来自 asyncpg，可能带出该行的值（Mitigation：gps_position 与 sensor_telemetry 现在没有密钥类字段；以后加字段要留意日志）
- Risk：进程被 SIGKILL（Docker 宽限期不够、OOM）时队列里尚未写库的推送会丢（Mitigation：Task 3.1 给 collector 配 stop_grace_period 40s；Spec v1.1 非功能「可靠」已写成本版接受的残余风险）
- Risk：`token_obtained_at` 从磁盘加载时为 0.0，宿主机刚开机 120 秒内 `time.monotonic()` 也小于 120，WS 被拒会被误判为「刚拿到 token」而少登一次（Mitigation：最多延迟到开机 2 分钟后的下一次重连，implementer B 判断极少发生）
- Assumption：对本地已有的 2026-08-21 ～ 2026-11-05 数据复跑 `lutetia backfill dingtek --from 2026-08-21 --to 2026-11-05` 新增 0 行（Confidence：Med）→ 2026-11-06 实测成立
- Assumption：python:3.9-slim 真跑需要拉镜像并装包，网络不通时按「3.9 真跑未知」记，不拿 AST 检查冒充（Confidence：Med）→ 2026-11-06 镜像已拉到、装包与用例在容器里跑通
- Assumption：postgres:16-alpine 官方镜像自带 pg_isready，compose 健康检查可直接用（Confidence：High，未亲测）

## Notes（简要要点）
- 2026-11-06: 实现与 Spec 已知差异两处——PushReceiver 对认不出的 payload 只打 warning 不计数（待定 5 默认要求计数，归 Task 1.3）；docker-compose 的 collector 只写 depends_on 不等库就绪，首次启动 migrate 可能靠 restart 重试才成功（归 Task 3.1）→ 前者 Task 1.3 已修
- 2026-11-06: Spec 用的是 SC-n / SCOPE-n 编号，没用 `[REQ-模块-编号]`，plan-lint 的覆盖检查跳过；DEV-PLAN 在 Task 标题与验收里手工引用 SC / SCOPE
- 2026-11-06: 本机 venv 是 Python 3.14，Spec 要求的 3.9 写法此前只靠自觉，Task 1.2 之后由测试守；3.14 上 `asyncio.TimeoutError` 就是 OSError 子类，F13 的区分度只有 3.9 容器真跑才有
- 2026-11-06: Bash 的 secret-exfil-guard 会拦命令文本里含 `.env` 字样的命令（即便只是写文件内容），落 DEV-PLAN 改用 Write 工具
- 2026-11-06: red-lock 实际走法——tester 把审查者的 attack1.py / attack2.py 改造成 pytest 红用例，主 Agent 亲跑看到失败后 `touch .claude/.red-verified`，再派 implementer；fix-spec-phase1.md（scratchpad）作 tester / implementer / reviewer 三方共用的修后行为契约
- 2026-11-06: code-reviewer 与 tester 的最终回传有两次只送到了「补充证据类型」那一段，完整回执要用 SendMessage 让它重发一遍再验收
- 2026-11-06: 审查三条反例的处理——反例 3（200 后写库失败即丢）已由重试 + 停机清队列解决；反例 1（静默按什么算）与反例 2（报警转发当位置）进 Spec 待定问题表，等用户答（TODO #10）
- 2026-11-06: 复核 Stage 2 结论——安全 grep 零命中、SQL 全参数化；dingtek.py 303 行（修 N-3 / N-4 后 306）超 300 上限，拆分排 Task 2.0；Spec 漂移 5 处已在 v1.1 补齐
- 2026-11-06: 容器里 `pip install .` 会在挂载的仓库目录留下 root 属主的 build/，要用容器 `rm -rf build` 清；3.9 真跑时 `| tail` 会吞掉 pytest 的退出码，看末行文本不看 exit
- Needs-Confirmation：Spec v1.1 修订等用户复述签字；两条新待定（静默口径、报警转发）等用户答

## Context Index（轻量索引）
- 需求：./Product-Spec.md（v1.1，2026-11-06，v1.0 由 TASK.md 转写、TASK.md 已退役）；变更：./Product-Spec-CHANGELOG.md；计划：./DEV-PLAN.md（含 Task 2.0 与 Task 3.1 stop_grace_period，待提交）
- 提交（main）：9d8cc7e 首版 → 48f97bd Task 1.2 + DEV-PLAN / progress 入库 → 060fd04 Task 1.1 / 1.3 修复与 24 条回归用例；工作树当前有 8 个文件未提交（TODO #8）
- git 身份：仓库本地 `user.name=zylimit`、`user.email=zylimitde@gmail.com`（2026-11-06 配）
- 本机数据库：docker 容器 lutetia-pg，127.0.0.1:15433，库 lutetia；2026-11-06 查得 device 17 台 / sensor_telemetry 141,545 行（rest 2026-08-21 ～ 2026-11-05，12 台里 10 台有 rest 行，2 台离线机只有 ws 推下来的最后值）/ gps_position 4 行（poll，raw 已由 sql/002 转成 object）/ api_call 1,105 条——来自上一 session 2026-11-05 20:20 ～ 20:31 UTC 的 backfill 与短暂 `lutetia run`
- 本机 Dingtek 调用量（2026-11-06 查 24 小时内）：timeseries 1944 / keys 72 / attributes 72 / devices 6 / refresh 2 / login 0
- 本机环境：venv Python 3.14.4、aiohttp 3.14.5、asyncpg 0.32.0、pytest 9.2.0、pytest-asyncio 1.4.1；docker compose 2.40.3；本机已有 python:3.9-slim / 3.12-slim / 3.14-slim 镜像；8080 空闲（2026-11-06）
- 测试基线：pytest 49 passed（2026-11-06 晚，首版 18 + 兼容闸 4 + 审查回归 27）；DB 用例连不上库自动 skip；python:3.9-slim 容器里解析器 + 兼容用例绿
- 修复契约与派单包：scratchpad fix-spec-phase1.md、brief-*.md；审查者攻击脚本 attack1.py / attack2.py、复核脚本 recheck.py（会话级临时文件，不入库）
- 厂商资料：docs/vendor/gps51/（README、API/、samples/）、docs/vendor/dingtek/（README、PDF、samples/）
- state/：gps51_token.json、dingtek_token.json（2026-11-06 04:19 / 04:20 本地时间生成，已 gitignore）
- Archive：无
