# 派单：Task 5.2 测试（tester，MEDIUM 档，先写测试后实现，红灯是预期）

Goal：新建 `tests/test_poi_store.py`（头行 `# risk: high`，数据库集成用例，连不上库自动 skip），并把 `tests/test_migrations.py` 的 `EXPECTED` 加上 `003_poi.sql`。使它们在实现者新建 `lutetia/sql/003_poi.sql` 与 `lutetia/poi_store.py` 之前红、实现后全绿。你不得写或改 lutetia/ 下任何代码。

Scope：只许新建 tests/test_poi_store.py、改 tests/test_migrations.py 的 EXPECTED 一处；可读 DEV-PLAN.md Phase 5 / Task 5.2 段、Product-Spec.md「数据与权限」里 poi 与 poi_cable_segment 两行及「POI 台账导入」功能条目、tests/test_db.py 与 tests/test_migrations.py 的 DB 连接与 skip 写法、lutetia/poi_import.py 与 lutetia/models.py 里的 PoiRecord / SegmentRecord 字段。测试里不要用 xlsx，直接在 Python 里构造 PoiRecord / SegmentRecord（合成数据，工单号只用 6000xx 段，如 RNT600001、BRG600002）。

Out of Scope：不得读 data/ 目录；不写 CLI 与 xlsx 用例（Task 5.3 / 已完成的 5.1）；不碰 lutetia/ 代码；不装依赖。

Existing Pattern：同 tests/test_db.py：用 DATABASE_URL，连不上或未设自动 skip；pytest-asyncio auto 模式；每个用例用事务外的清理（truncate poi, poi_cable_segment）保证互不影响，**只清这两张表，不碰其它表**；Python 3.9 写法。

Business Context：运维要的是「导进去、再导一次不变、坏文件不留半份」。Spec v1.8 数据与权限 poi / poi_cable_segment 两行、SC-12 反向指标「失败整批回滚」「消失的单标台账已无而不是删」。

接口约定（实现者按此实现，你按此断言）：
 - 迁移文件 `lutetia/sql/003_poi.sql`，两表：`poi(poi_no text PRIMARY KEY, uci, subcon, site_ville, commune_code, category, status_raw text, occ_week_from int, occ_week_to int, occ_date_from date, occ_date_to date, received_date date, planned_op_date date, in_ledger boolean NOT NULL DEFAULT true, content_sha text NOT NULL, raw_sha text NOT NULL, raw jsonb, first_imported_at timestamptz NOT NULL DEFAULT now(), imported_at timestamptz NOT NULL DEFAULT now())`；`poi_cable_segment(poi_no text NOT NULL REFERENCES poi(poi_no) ON DELETE CASCADE, seq int NOT NULL, cable_category, cable_type, infra text, length_km numeric, weight_t numeric, ref_min_t numeric, ref_avg_t numeric, ref_max_t numeric, raw jsonb, PRIMARY KEY (poi_no, seq))`；三个索引 poi(uci)、poi(subcon)、poi(occ_week_from)；全部 IF NOT EXISTS，重复执行不报错，不碰现有五张表与两个视图。
 - `lutetia.poi_store.apply_ledger(pool, pois, dry_run=False) -> Dict[str, int]`，返回键 `new`、`updated`、`unchanged`、`raw_refreshed`、`gone`（初值 0）。一个事务内：
   · 库里没有该 poi_no → new（写 poi 行与全部段）；
   · content_sha 相同且 in_ledger 为真且 raw_sha 相同 → unchanged；
   · content_sha 相同、in_ledger 为真、仅 raw_sha 不同 → raw_refreshed（只刷新 poi.raw 与各段 raw、raw_sha、imported_at，业务字段与段不动，不计 updated）；
   · content_sha 不同，或原来 in_ledger=false 现在回来了 → updated（upsert poi 行，删旧段重插新段，in_ledger 置 true）；
   · 库里有而本次没有的 poi_no → in_ledger=false，计 gone，不删行不删段（已经是 false 的不重复计）；
   · dry_run=True：算完计数后整个事务回滚，两张表行数与内容和调用前一致，返回的计数照常；
   · 任何语句出错整个事务回滚、异常向上抛，两张表与调用前一致；全部 SQL 参数化。
 - 返回的计数之和约束：new + updated + unchanged + raw_refreshed == 本次传入的工单数。

必须覆盖的用例（合成数据）：
 1. 库空时导入 2 个工单（共 3 段）→ {new:2, updated:0, unchanged:0, raw_refreshed:0, gone:0}；poi 2 行、段 3 行；段按 seq 存。
 2. 原样再导 → {0,0,2,0,0}，行数不变，imported_at 不变（unchanged 不刷新时间）。
 3. 把一个工单第 2 段的 weight_t 改了（content_sha 变）再导 → updated:1, unchanged:1；该工单仍是 2 段且新重量在库里；另一个工单未动。
 4. 只改 raw_sha 不改 content_sha（给同一工单换一个 raw 字典、raw_sha）→ raw_refreshed:1，不计 updated；库里 raw 已刷新、业务字段与段不变。
 5. 导入只含第 1 个工单的文件 → 第 2 个工单 in_ledger=false、gone:1、行与段都还在；再导同一份 → gone:0（已是 false 不重复计）；然后重新导入含第 2 个工单的文件 → 第 2 个工单 updated:1 且 in_ledger 回 true。
 6. 毒行：同一调用里给一个工单两个相同 seq 的段（主键冲突）→ 抛异常，两张表行数与调用前一致（先放 1 个正常工单进库，调用前后断言其行数与内容都不变，证明整批回滚而不是只回滚毒行）。
 7. dry_run=True：对空库与对已有数据各一次，返回计数正确，调用后两张表与调用前逐行一致。
 8. 没有段的工单（segments 为空）能进库，poi 有行、段 0 行。
 9. 迁移幂等：连续执行 003_poi.sql 两次不报错；不改现有五张表（表名与列数不变）。
 10. tests/test_migrations.py 的 EXPECTED 加 `003_poi.sql`（按现有写法，保持升序）。
 11. 一个 PoiRecord 的 raw 含中文与特殊字符（引号、换行）也能存取回来逐字相同。

Verification：`python -m pytest tests/test_poi_store.py tests/test_migrations.py -q -p no:cacheprovider` 必须红（ModuleNotFoundError: lutetia.poi_store 或迁移缺表），贴原始输出，说明红是因为实现不存在而不是测试写错；shell 里默认没设 DATABASE_URL（所以 DB 用例会 skip）。跑 DB 用例时在命令前显式带上本机合成测试库的连接串（开发用常量，不是密钥，lutetia-pg 容器 127.0.0.1:15433，库里 0 行设备）：`DATABASE_URL=postgresql://lutetia:lutetia@127.0.0.1:15433/lutetia python -m pytest tests/test_poi_store.py tests/test_migrations.py -q -p no:cacheprovider`。**不得连别的库**：机器上还有生产 compose 的 lutetia-db-1 / lutetia-collector-1 容器（不发布端口，不是你的目标），不要碰；不读任何 .env 文件内容。先 `source .venv/bin/activate`。红灯必须是在 DB 真连上的前提下红（贴 skip 数为 0 的汇总），不能是因为 skip 而「没红」。工具调用预算约 20 次。

Escalation：接口约定与例子冲突、DATABASE_URL 没设或连不上（则用例会 skip，要如实报告「红灯无法验证」并返回主 Agent）、需要改 lutetia/ 代码的，返回主 Agent。

回执用统一信封（Status / Changed / Verified / Not verified / Business assumptions / Counter-examples / Domain findings / Needs review by / Evidence）。
