# 派单：Task 5.2 实现（implementer，MEDIUM 档，sonnet）

Goal：新建 `lutetia/sql/003_poi.sql` 与 `lutetia/poi_store.py`，使 tests/test_poi_store.py、tests/test_migrations.py 全绿，且全量不比改动前多红。测试是独立 tester 写的，是你的需求规格：先读全部断言再实现；不得改测试（觉得测试错了就返回主 Agent 附反例）。

Scope：只许新建上面两个文件。可读 DEV-PLAN.md Phase 5 / Task 5.2 段、Product-Spec.md「数据与权限」poi 与 poi_cable_segment 两行、lutetia/db.py（连接池与 upsert 风格，不改它）、lutetia/sql/001_schema.sql（建表风格）、lutetia/poi_import.py 的 PoiRecord / SegmentRecord 字段。

Out of Scope：不碰 cli.py、docker-compose.yml、README、db.py、现有迁移文件与现有五张表；不装依赖；不读 data/；不 commit。

Existing Pattern：迁移文件全部 IF NOT EXISTS、中文注释写为什么；asyncpg，参数化 SQL（$1…），jsonb 列已由连接池的 codec 编解码（见 db.py _init_conn，直接传 dict）；Python 3.9 写法；源码文件 < 300 行。

Business Context：运维导入手工 Excel 台账，要「导进去、再导一次不变、坏文件不留半份」。apply_ledger 的语义（事务、new / updated / unchanged / raw_refreshed / gone 的判定、dry_run 回滚）全部以 tests/test_poi_store.py 与 DEV-PLAN.md Task 5.2 为准。两个指纹：content_sha 变化 = 业务字段或段变了 → updated；只有 raw_sha 变化 → 只刷新 raw 相关列、计 raw_refreshed、不算 updated；库里有而本次没有 → in_ledger=false 计 gone，不删行不删段，已是 false 的不重复计；原来 in_ledger=false 现在回来了 → updated。

Verification：用本机合成测试库跑（shell 里默认没设 DATABASE_URL，所以不带它 DB 用例会 skip，不算数）：`DATABASE_URL=postgresql://lutetia:lutetia@127.0.0.1:15433/lutetia python -m pytest tests/test_poi_store.py tests/test_migrations.py -q -p no:cacheprovider`（连接串是开发用常量，容器 lutetia-pg；机器上的 lutetia-db-1 / lutetia-collector-1 是生产，不是你的目标，不要碰）；再跑全量 `python -m pytest -q -p no:cacheprovider`（不带 DATABASE_URL，原样）与 `python -m pytest tests/test_compat.py -q -p no:cacheprovider`；`wc -l lutetia/poi_store.py`。回执里贴 DB 用例的 skip 数必须为 0。工具调用预算约 20 次。新建文件用 `wc -l` + `git status` 认 `??`，不用 git diff。

Escalation：测试断言与 DEV-PLAN / Spec 冲突、需要改现有文件或装依赖、DB 连不上——返回主 Agent，不得自行扩大范围。

回执用统一信封（Status / Changed / Verified / Not verified / Business assumptions / Counter-examples / Domain findings / Needs review by / Evidence）。
