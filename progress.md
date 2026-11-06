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

## TODO（权威待办清单）
- [P0][OPEN][#1] Task 1.1 首版对照 Spec 审查并修 HIGH 缺陷——HIGH 档，code-reviewer 全三 Stage，HIGH 修完同一轮复核（Context：DEV-PLAN.md Phase 1）
- [P0][OPEN][#2] Task 1.2 新建 tests/test_compat.py：3.9 语法 / 注解类型联合 / 3.10+ 标准库 AST 检查 + 密码前缀扫描，LOW 档（Context：DEV-PLAN.md Phase 1）
- [P0][OPEN][#3] Task 1.3 PushReceiver 补 unrecognised 计数进 /health，本机四步 curl 实测 SC-3，LOW 档（Context：DEV-PLAN.md Phase 1）
- [P1][OPEN][#4] `.serena/` 加进 .gitignore，随第一个代码提交一起入库（Context：2026-11-06 发现未跟踪）
- [P1][OPEN][#5] Spec SC-1 「当前基线 0」改成实数并记 CHANGELOG——Phase 1 收口时按 product-spec-builder 直推档改（Context：Product-Spec.md 成功判据表）
- [P1][OPEN][#6] Phase 3 开工前用户回答待定 3（目标机 Python 版本）与待定 4（推送接收端 HTTPS / 鉴权）（Context：Product-Spec.md 待定问题表、DEV-PLAN.md 开工前置）
- [P1][OPEN][#7] Phase 2 Task 2.1（tests/test_status.py 失联判定回归）与 Phase 3 Task 3.1（compose 健康检查 + 部署文档随机路径）按 DEV-PLAN.md 顺序排在 Phase 1 之后（Context：DEV-PLAN.md Phase 2 / Phase 3）

## In Progress
- 无

## Done（最近完成的放前面）
- 2026-11-06: DEV-PLAN.md 生成，193 行、3 个 Phase、5 个 Task，plan-lint 通过（evidence：./DEV-PLAN.md；`bash .claude/scripts/plan-lint.sh DEV-PLAN.md Product-Spec.md` 输出「plan-lint: 通过」，Spec 无 REQ 编号故覆盖检查跳过）
- 2026-11-06: recap 完成——读 Product-Spec.md v1.0 与 CHANGELOG，核工作树干净、首版提交 9d8cc7e、pytest 18 passed（evidence：`python -m pytest -q -p no:cacheprovider` 输出 18 passed in 0.79s）

## Risks & Assumptions
- Risk：首版 1600 行从未对照 Spec 审过，而 Spec 又是从代码转写的，「代码等于 Spec」是循环论证（Mitigation：Task 1.1 派 fresh code-reviewer 独立审一遍）
- Risk：上一 session 2026-11-05 的 backfill 与短暂 run 没记进任何文档，本地库状态只能靠查库反推（Mitigation：实况已记进 Context Index；Phase 1 复跑回补拿幂等证据）
- Assumption：对本地已有的 2026-08-21 ～ 2026-11-05 数据复跑 `lutetia backfill dingtek --from 2026-08-21 --to 2026-11-05` 新增 0 行（Confidence：Med）
- Assumption：python:3.9-slim 真跑需要拉镜像并装包，网络不通时按「3.9 真跑未知」记，不拿 AST 检查冒充（Confidence：Med）
- Assumption：postgres:16-alpine 官方镜像自带 pg_isready，compose 健康检查可直接用（Confidence：High，未亲测）

## Notes（简要要点）
- 2026-11-06: 实现与 Spec 已知差异两处——PushReceiver 对认不出的 payload 只打 warning 不计数（待定 5 默认要求计数，归 Task 1.3）；docker-compose 的 collector 只写 depends_on 不等库就绪，首次启动 migrate 可能靠 restart 重试才成功（归 Task 3.1）
- 2026-11-06: Spec 用的是 SC-n / SCOPE-n 编号，没用 `[REQ-模块-编号]`，plan-lint 的覆盖检查跳过；DEV-PLAN 在 Task 标题与验收里手工引用 SC / SCOPE
- 2026-11-06: 本机 venv 是 Python 3.14，Spec 要求的 3.9 写法此前只靠自觉，Task 1.2 之后由测试守
- 2026-11-06: Bash 的 secret-exfil-guard 会拦命令文本里含 `.env` 字样的命令（即便只是写文件内容），落 DEV-PLAN 改用 Write 工具

## Context Index（轻量索引）
- 需求：./Product-Spec.md（v1.0，2026-11-06，由 TASK.md 转写，TASK.md 已退役）；变更：./Product-Spec-CHANGELOG.md；计划：./DEV-PLAN.md
- 首版提交：9d8cc7e（main，工作树干净，2026-11-06）
- 本机数据库：docker 容器 lutetia-pg，127.0.0.1:15433，库 lutetia；2026-11-06 查得 device 17 台 / sensor_telemetry 141,545 行（rest 2026-08-21 ～ 2026-11-05，12 台里 10 台有 rest 行，2 台离线机只有 ws 推下来的最后值）/ gps_position 4 行（poll）/ api_call 1,105 条（dingtek timeseries 996、gps51 共 8）——来自上一 session 2026-11-05 20:20 ～ 20:31 UTC 的 backfill 与短暂 `lutetia run`
- 本机环境：venv Python 3.14.4、aiohttp 3.14.5、asyncpg 0.32.0、pytest 9.2.0、pytest-asyncio 1.4.1；docker compose 2.40.3；本机已有 python:3.12-slim / 3.14-slim 镜像，无 3.9；8080 空闲（2026-11-06）
- 测试基线：pytest 18 passed（2026-11-06）；DB 用例连不上库自动 skip
- 厂商资料：docs/vendor/gps51/（README、API/、samples/）、docs/vendor/dingtek/（README、PDF、samples/）
- state/：gps51_token.json、dingtek_token.json（2026-11-06 04:19 / 04:20 本地时间生成，已 gitignore）
- Archive：无
