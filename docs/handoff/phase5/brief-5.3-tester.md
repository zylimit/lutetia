# 派单：Task 5.3 测试（tester，MEDIUM 档，先写测试后实现，红灯是预期）

Goal：新建 `tests/test_cli_import.py`（头行 `# risk: high`），使它在实现者给 `lutetia/cli.py` 加 `import poi` 子命令、给 docker-compose.yml 与 README 加条目之前红、实现后全绿。你不得改 lutetia/、docker-compose.yml、README。

Scope：只许新建 tests/test_cli_import.py。可读 DEV-PLAN.md Phase 5 / Task 5.3 段、Product-Spec.md FLOW-5 与「POI 台账导入」功能条目、tests/xlsx_builder.py（造合成 xlsx）、tests/test_status.py（现有 CLI 用例写法）、lutetia/cli.py、lutetia/poi_import.py、lutetia/poi_store.py（若已存在）。

Out of Scope：不得读 data/；不写解析或入库层用例（5.1 / 5.2 已有）；不碰生产库；不装依赖。

Existing Pattern：CLI 用例用子进程 `python -m lutetia.cli …`（或 `main(argv)` 配 pytest 的 capsys），连库的用例仅在 DATABASE_URL 可连时运行否则 skip；tests/ 里工单号只用 6000xx 段合成号；Python 3.9 写法。

Business Context：FLOW-5：华为项目组的小雷把新版台账放到主机上，一条命令导入、看汇总数字就知道对不对。

接口约定：`lutetia import poi FILE [--dry-run]`。输出到标准输出，格式固定（五行里 dry-run 行只在 --dry-run 时出现，放在最前）：
```
dry-run: nothing written
read: N POI / M segments (K POI without cable detail)
result: A new, B updated, C unchanged, R raw refreshed, D gone from ledger
cleaned: uci_normalised=X trimmed_cells=Y na_to_empty=Z segment_no_cable_type=V not_a_number=Q; occ_unparsed=W
suspicious: none            （或工单号逗号加空格分隔）
```
错误：`LedgerError` / `XlsxError` → 标准错误打印 `error: <原因>`，退出码 1，**不连数据库**（用一个连不上的 DATABASE_URL 如 `postgresql://x:x@127.0.0.1:1/x` 也要得到同样的 error 行与退出码 1，证明没连库）；文件不存在 → `error: file not found: <路径>`，退出码 1。成功退出码 0。除可疑工单号外不得打印任何行内容（分包商名、市镇、重量、型号都不得出现在输出里）。

必须覆盖：
 1. 合成 xlsx（3 个工单、其中 1 个无段，共 3 段）+ lutetia-pg：首次导入输出五行格式对（read: 3 POI / 3 segments (1 POI without cable detail)；result: 3 new, 0 updated, 0 unchanged, 0 raw refreshed, 0 gone from ledger），库里 poi 3 行、段 3 行；原样再导一次 result 为 0 new, 0 updated, 3 unchanged；改一段重量重导 → 1 updated。
 2. `--dry-run`：首行 `dry-run: nothing written`，result 计数照常，导入前后两张表行数不变。
 3. 缺 `POI` 表头的合成文件 → stderr 含 `error: missing column: POI`、退出码 1，且用连不上的 DATABASE_URL 也一样（不连库）。
 4. 路径不存在 → `error: file not found`、退出码 1。
 5. 输出不泄漏行内容：用含独特合成分包商名 `SUBCON-ZZ9` 与市镇名 `COMMUNE-ZZ9` 的文件导入，断言标准输出与标准错误都不含这两个字符串；含畸形工单号的文件 suspicious 行含该号。
 6. `build_parser()` 里存在 `import poi`，`--dry-run` 默认 False。
 7. docker-compose.yml 的 collector 服务 volumes 含 `./data/poi:/ledger:ro`（按文本断言，且同一文件里原有的 `lutetia-state:/data` 仍在）；`.dockerignore` 或 Dockerfile 保证 `data/` 不进镜像（断言 Dockerfile 的 COPY 行只复制 pyproject.toml、README.md、lutetia）；README.md 含 `lutetia import poi`。
 8. 连库的用例用显式连接串 `postgresql://lutetia:lutetia@127.0.0.1:15433/lutetia`（开发用常量，容器 lutetia-pg，合成库）；每个用例开始前只 truncate poi、poi_cable_segment 两张表，不碰其它表；**不得连别的库**，机器上的 lutetia-db-1 / lutetia-collector-1 是生产，不要碰。

Verification：`DATABASE_URL=postgresql://lutetia:lutetia@127.0.0.1:15433/lutetia python -m pytest tests/test_cli_import.py -q -p no:cacheprovider` 必须红且 skip 数为 0（红是因为实现不存在）；贴原始输出。工具调用预算约 20 次。先 `source .venv/bin/activate`。

Escalation：接口约定冲突、DB 连不上（如实报「红灯无法验证」）、需要改 lutetia/ 代码的，返回主 Agent。

回执用统一信封。
