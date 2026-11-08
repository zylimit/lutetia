# 恢复演练记录

对应 DEV-PLAN Task 6.3、DFX 场景 RS-1。每次演练在文末表格加一行。

## 演练证明什么

- 备份文件真的能恢复：在一次性 `postgres:16-alpine` 容器里 `pg_restore` 成功。
- 恢复出的七张表（device、gps_position、sensor_telemetry、sensor_attribute、api_call、poi、poi_cable_segment）行数，落在该备份 `backup_run.row_counts`（dump 前）与 `row_counts_after`（dump 后）之间，含两端：`前 ≤ 恢复 ≤ 后`。采集在 dump 期间仍在写入、表只增不删，所以不要求相等；例：dump 前 160,000、后 160,008，恢复 160,003 通过，159,999 失败。
- 从下载到行数核对完成的耗时（RTO ≤ 4 h 候选的实测依据，演练后写回 DFX-Spec 第 2 维）。
- 可选：上传密钥删不掉备份对象（THR-6，COS 的「只写不删」权限真生效）。

演练全程不碰生产库与生产卷（生产库只被只读地查一次 `backup_run`）；临时容器随机名、独立网络、无卷、随机密码，退出时无论成败都删。

## 怎么跑

在 fra 宿主机的仓库目录，`db` 服务在跑。

**输入方式一：用户先下载**——从 COS 控制台把 `daily/lutetia-<UTC 时间戳>.dump` 下载到 fra（保持原文件名，脚本按文件名找 `backup_run` 行）：

```
deploy/restore-drill.sh --file /path/to/lutetia-20261110T013000Z.dump
```

**输入方式二：脚本自己下载最新一份日备**——需要读权限（见下方前置）：

```
COS_BUCKET=<桶名> COSCLI_READ_CONFIG=/etc/lutetia/coscli-read.yaml deploy/restore-drill.sh --from-cos
```

**删除测试**（两种方式都可加，有意尝试删除该备份对象）：

```
COS_BUCKET=<桶名> COSCLI_CONFIG=<写配置，同 backup.sh> COSCLI_READ_CONFIG=<只读配置> deploy/restore-drill.sh --file … --check-delete-denied
```

判定不看 `coscli rm` 的退出码（coscli 丢弃删除返回值、先 HEAD、不加 -f 还等确认，退出码分不清「被拒」与「静默失败」）。脚本三步：只读配置 `ls` 确认对象在 → 写配置 `rm -f`（退出码只记日志）→ 只读配置再 `ls`。对象仍在记 PASS；对象没了大声 FAIL 并非零退出——那份备份已经没了，立刻修密钥策略并重新备份；复查 `ls` 出错记 FAIL「无法确认」，不当 PASS。

PASS 只证明「用 coscli 删不掉」，不等于「这把密钥没有删除权限」：coscli 删除前先 HEAD 对象，若写密钥有删除权限却没有 HEAD 权限，删除请求根本发不出去，对象还在，脚本照样记 PASS，而这把密钥用原生 API 其实能删（2026-11-09 Task 6.3 复核，依据 coscli v1.0.9 源码，未经真 COS 实测）。所以每次演练记 PASS 后，演练人还要到 COS 控制台打开这把写密钥（子账号）的策略核对一眼：只许写入类动作，不得出现 `cos:DeleteObject`、`cos:DeleteMultipleObject` 或 `cos:*`；结果写进下表「删除测试」一栏（如「PASS，策略已核」）。

输出：每表一行 `table 前 ≤ 恢复 ≤ 后  OK|FAIL`，再一行总耗时；任一 FAIL 或删除测试未通过则退出码非零。

## 用户侧前置

- `--from-cos`：备份上传密钥按设计只有写权限（THR-6），读不了桶。要另建一把**只读**子账号密钥，在 fra 上生成对应的 coscli 配置文件，路径经 `COSCLI_READ_CONFIG` 传入（脚本不读不打印其内容）。
- 不想建只读密钥：用方式一，从 COS 控制台手动下载。
- `--check-delete-denied`：用备份用的写配置（`COSCLI_CONFIG`，不设则 coscli 默认配置）尝试删除，**同时必须有只读密钥配置 `COSCLI_READ_CONFIG`**（`--file` 模式也要，用来确认删除前后对象在不在），需要 `COS_BUCKET`。没有只读密钥就不能做这项检查。

## 演练结果

| 日期 | 备份对象 | device 前/恢复/后 | gps_position 前/恢复/后 | sensor_telemetry 前/恢复/后 | sensor_attribute 前/恢复/后 | api_call 前/恢复/后 | poi 前/恢复/后 | poi_cable_segment 前/恢复/后 | 耗时 | 删除测试 | 操作人 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| | | | | | | | | | | | |
