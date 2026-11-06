# 变更记录

## [v1.0] - 2026-11-06
- 初始版本：由 TASK.md（2026-11-06 版）转写而来，TASK.md 自本版起退役。
- 转写时以代码现状为准的两处：命令名 `lutetia`（TASK.md 写的是 `collector`）；每日回补窗口 2 天 / 03:00 UTC、GPS51 日预算 1400 / 调用间隔 6 秒、status 失联阈值取 3 小时与 2 倍 uploadInterval 的大者，这些数字 TASK.md 没写，按 config.py 默认值记入并标 `[推断]`。
- 六条未决进「待定问题」表：volt / rsrp 换算系数、推送非 200 的重试行为、目标机 Python 版本、接收端 HTTPS 与鉴权、推送 JSON 外层形态、GPS 位置的 GDPR 适用性。
- 仓库决定（非需求）：.claude/ 脚手架目录不入库。
