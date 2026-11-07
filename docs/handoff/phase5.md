# Phase 5 交接：POI 台账导入（2026-11-08）

用户决定在别处接着开发。本文说清到哪了、从哪继续、哪些不能做。需求在 Product-Spec.md v1.8（SCOPE-16、SC-12、FLOW-5、数据与权限里 poi / poi_cable_segment 两行），计划在 DEV-PLAN.md Phase 5，进度与决策在 progress.md（TODO #76 ～ #78）。

## 现状

| Task | 状态 | 在哪 |
|---|---|---|
| 5.1 xlsx 读取器 + 台账映射与清洗 | 完成、已验收 | main：`lutetia/xlsx_min.py`、`poi_clean.py`、`poi_import.py`，测试 105 个全绿；code-reviewer 无 HIGH |
| 5.2 迁移 `003_poi.sql` + `poi_store.apply_ledger` | 只有测试（红） | 分支 `phase5-wip`：`tests/test_poi_store.py`、`tests/test_migrations.py` 的 EXPECTED 已加 `003_poi.sql`；实现不存在，按设计是红的，所以没放进 main |
| 5.3 `lutetia import poi` 命令 + compose 只读挂载 + README | 未开始 | 任务书 `docs/handoff/phase5/brief-5.3-tester.md` |
| 5.4 生产导入 | 未开始，要用户亲敲 `/release-builder` | DEV-PLAN Task 5.4 |

## 从哪继续

1. `git fetch && git checkout phase5-wip`，先读 `docs/handoff/phase5/brief-5.2-tester.md` 里的接口约定（表结构、`apply_ledger` 返回键 `new / updated / unchanged / raw_refreshed / gone`、必须覆盖的 11 条用例），再按 `brief-5.2-implementer.md` 实现 `lutetia/sql/003_poi.sql` 与 `lutetia/poi_store.py`，让 5.2 的测试转绿，合回 main。
2. 5.3：先按 `brief-5.3-tester.md` 写红用例，再实现 `cli.py` 的 `import poi` 子命令、`docker-compose.yml` 一行只读挂载 `./data/poi:/ledger:ro`、README 命令表。输出格式固定，见任务书。
   5.2 实现注意：numeric 列写入前用 `Decimal(str(值))`，别把 float 直接传给 asyncpg；`apply_ledger` 返回五个键含 `raw_refreshed`；tests/test_poi_store.py 有本机主机守卫，只会连 127.0.0.1 的库。
3. 先修 #77（`xlsx_min.py` 一次读全的回归，一行改动），再视情况处理 #78 的残留。
4. 5.4 发版与生产导入由用户亲敲 `/release-builder`，不得代做。

流程不变：每个 Task 先由与实现者不同的 tester 写红用例，再 implementer 实现，MEDIUM 档加一轮 code-reviewer 只跑 Stage 0 + 1；一轮只 HIGH 阻断。

## 不能做的事

- **真台账不进 Git、不出欧洲**：`data/poi/` 下五份 xlsx 只在法兰克福 fra 的 `~/code/lutetia/data/poi/`，`.gitignore` 已排除 `data/`。别处开发只用合成 xlsx（`tests/xlsx_builder.py` 造），工单号只用 6000xx 段。需要对真文件对账的步骤（`--dry-run` 汇总应为 117 个工单 / 99 个电缆段 / 92 个无明细、计划重量合计约 244 t）必须回 fra 跑，且只看汇总数字、不打印行内容。
- **DB 用例要真跑**：shell 里默认没设 `DATABASE_URL`，DB 用例会被 skip，等于没测。起一个合成测试库后带上连接串跑，fra 上是 `DATABASE_URL=postgresql://lutetia:lutetia@127.0.0.1:15433/lutetia`（容器 `lutetia-pg`）。fra 上还有生产 compose 的 `lutetia-db-1` / `lutetia-collector-1`，不是测试目标，别碰；生产检出 `~/lutetia` 别在里面改代码。
- 看板与 API 只读（Pinned）：`lutetia/web/**` 不许有写路径；导入只走命令，不做上传按钮。
- 代码按 Python 3.9 写法；凭据只从环境变量读；源码文件 < 300 行。
- 归档脚本 `.claude/scripts/progress-archive.mjs` 对 Decisions / Notes 的保留方向有 bug（保留最旧、搬走最新），修之前别跑，见 `~/cc-base-prompt-progress-archive.md`（fra 上，交给 cc-base 修）。

## 已定的取舍（别重问）

电缆段判据任一段字段非空即成段；两个指纹 content_sha / raw_sha；只用标准库读 xlsx；表结构先于整体架构定下，之后可能随架构调整（用户 2026-11-07 批准）；本版不算完成率、不接 operation 表。
