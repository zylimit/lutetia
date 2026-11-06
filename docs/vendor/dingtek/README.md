# Dingtek Cloud（DC414 井盖传感器）数据获取调研 — 2026-11-06

账号：见 .env 的 DINGTEK_USER，角色 CUSTOMER_USER（只能看本客户下设备，不能建设备/改配置）。
平台：`https://cloud.dingtek.com` 就是一套 **ThingsBoard**（接口路径、`X-Authorization: Bearer`、`/api/plugins/telemetry/...`、`/api/ws/plugins/telemetry` 全部是 TB 标准），所以 TB 官方 REST / WebSocket 文档都适用，不止 PDF 里那 4 个接口。

## 设备
12 台 DC414（Dingtek DC41x 智能井盖系列的 4G 版），全部在巴黎（2 台 Boulogne-Billancourt 48.833/2.260，10 台埃菲尔铁塔附近 48.858/2.298）。
- 7 月装的 2 台（862288…）固件 4.3，8 月 17 日后离线（active=False）。
- 8 月 19 日装的 10 台（864317…）固件 4.4，全部在线，最后上报 2026-11-05。

## 数据模型
遥测 key（每条上报一起来）：`level`（水位/液位，阈值 levelThreshold=30）、`temperature`（℃）、`volt`（×0.01V，360=3.60V）、`rsrp`（×0.1dBm，-670=-67dBm）、`alarmLevel`、`alarmBattery`、`alarmFall`（井盖倾倒/移位）、`angle`（仅 4.3 固件）、`FSM`（振动状态机：none / normal_vibration）、`frameCounter`（帧序号，可用来算丢包）。
属性：`uploadInterval`（小时）、`detectInterval`、`fallThreshold`、`levelThreshold`、`workMode`、`firmware`、`wireless=4G`、`devEui`、`latitude/longitude`（装机时写入，不是实时定位）、`active`、`lastActivityTime`。
近 7 天实测（864317087586940，uploadInterval=1）：每 61 分钟一个心跳点，偶发突发批量（最多一次 354 点，推测事件触发或补传），7 天 826 点，frameCounter 跨度 833 → 丢 7 帧。
目前 12 台 level 全为 0、无报警（/api/alarm 返回 0 条）。

## 接口（已验证）
| 用途 | 调用 |
|---|---|
| 登录 | `POST /api/auth/login` `{"username","password"}` → `token`（JWT）、`refreshToken`。限 5 次/分钟/IP，务必缓存 token |
| 设备列表 | `GET /api/user/devices?pageSize=100&page=0&sortProperty=name` → `data[].id.id` 是 UUID，后续都用它 |
| 遥测 key | `GET /api/plugins/telemetry/DEVICE/{uuid}/keys/timeseries` |
| 属性 | `GET /api/plugins/telemetry/DEVICE/{uuid}/values/attributes` |
| 最新值 | `GET /api/plugins/telemetry/DEVICE/{uuid}/values/timeseries`（不带 startTs） |
| 历史 | 同上 + `keys=&startTs=&endTs=&limit=1000`（毫秒；加 `orderBy=ASC` 可取最早点） |
| 报警 | `GET /api/alarm/DEVICE/{uuid}?pageSize=10&page=0` |
| 实时推送 | `wss://cloud.dingtek.com/api/ws/plugins/telemetry?token=` 握手返回 101，可用 TB 标准订阅协议，不用轮询 |

## 保留与配额
- PDF 说保留「最多 1 个月」，实测最早点 2026-08-21，已有 77 天；但这是目标不是承诺，**必须自己落库**。
- 无固定吞吐保证；付费服务，到期一周后可能删数据。
- 只有登录限频是明确数字；其它是 fair use。

## 建议
1. 自己的服务先用 REST 把 8 月 21 日至今全量拉回来落库（12 台 × 5 个 key，按天分段 limit=1000）。
2. 之后用 WebSocket 订阅 12 台的 timeseries 实时入库，REST 每天兜底补一次。
3. 和 GPS51 那套统一成一个采集服务：GPS51 用转发推送，Dingtek 用 WS 订阅。

## 文件
- `Guide_of_Dingtek_Sensor_Integration-V2.pdf`：原始文档
- `samples/`：设备列表、12 台设备属性+最新值、7 天历史
- `dingtek_probe.py` / `dingtek_probe2.py`：探测脚本，凭据走环境变量 `DINGTEK_USER` / `DINGTEK_PWD`
