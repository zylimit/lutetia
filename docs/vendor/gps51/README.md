# GPS51 (途强物联) 数据获取调研 — 2026-11-06

账号：见 .env 的 GPS51_USER（usertype=2，由 途强物联 创建，multilogin=1 → API 登录不会踢掉网页会话）

## 两个入口
| 入口 | URL | 白名单 | 说明 |
|---|---|---|---|
| OpenAPI（官方） | `http://api.gps51.com/openapi?action=X&token=T&serverid=S` | 强制（8904） | 生产用这个；配额规则在这层执行 |
| WebAPI（网页端自用） | `https://www.gps51.com/webapi?action=X&token=T&serverid=S&extend=self` | 不查 | 同一个 token 两边通用，返回完全一致；非官方，不要上生产 |

- 全部 HTTP POST，body 为 JSON，token/serverid 放 URL。
- 登录：`action=login`，body `{"type":"USER","from":"WEB","username":..,"password":md5小写32位,"browser":..}`；token 24h，建议 23h 刷新一次。
- 登录返回里还有 `websocketserver: wss://appserver2.gps51.com`（网页端实时推送通道，`?serverid=2`，连上后发 `login-{token}-web`，收 JSON；未在文档里，不建议依赖）。

## 配额（OpenAPI 文档）
- 每账号每天 1440 次 + 有效续费设备数 × 5
- 轨迹接口（querytracks）每设备 5 次/天，且明文禁止服务器自动同步轨迹
- 每 IP 10 次/分钟
- 每账号每天最多改 5 次白名单
- 错误码：8902 IP 频率、8903 账号限制、8904 IP 不在白名单、8905 次数用完、8906 action 禁用、9903 token 过期、9906 token 不存在

## 推荐数据获取方式（按优先级）
1. **数据转发（推送）** — 后台「转发平台列表」配置，协议有 Tcp/Udp Socket、Http Json、Http Sign Json、Http Alarm、WebSocket、JT/T 809 等。不占配额，实时。当前账号 forwards=[]（未配置）。推送 JSON 字段见 `API/数据转发/`。
2. **lastposition 增量轮询** — 传回上次返回的 `lastquerypositiontime`，无变化时 records=[]（已验证）。1 次/分钟 ≈ 1440 次/天，刚好吃满配额。
3. **querytracks 历史轨迹** — 仅按需补数/人工查看。实测 1 天 548km 返回 928 条、758KB、每条 50 字段。
4. **报表类** — reportmileagedetail（日里程）、querytrips（行程）、reportparkdetailbytime（停留）、reportalarm（报警）、reportaccsbytime（ACC）。

## 实测坑
- `speed` 文档写「米」，实际是 **米/小时**（实测最大 122232 = 122 km/h）。
- 无数据时 querytracks 返回 `records: null`（不是 []），querytrips 返回 `totaltrips: []`，要判空。
- 温度无效值：轨迹里是 65535，lastposition 里是 536870911，两个哨兵值不同。
- 时间全部是 UTC 毫秒；查询参数用 `yyyy-MM-dd HH:mm:ss` + `timezone`(默认 8)。
- 坐标 WGS84，字段名 `callat/callon`（推送里是 `lat/lon`）。
- `validpoistiontime` 拼写错误是官方沿用的。

## 当前设备（5 台，1 个分组 Default）
| deviceid | 类型 | 状态 | 最后活跃(UTC) | 位置 |
|---|---|---|---|---|
| 4072400634 | 53 JH123 天禾充电设备 | 正常 | 2026-10-14 | 巴黎 |
| 4072400915 | 53 JH123 天禾充电设备 | 正常 | 2026-10-19 | 巴黎 |
| 4072401353 | 53 JH123 天禾充电设备 | 过期 | 2026-08-07 | 西安 |
| 4072407731 | 1 JT808 部标接线设备 | 过期 | 2026-06-30 | 哈拉雷 |
| 4072407783 | 1 JT808 部标接线设备 | 体验 | 从未上线 | - |

## 文件
- `API/`、`API调用说明.md`：厂家 wiki 全量导出（63 篇）
- `samples/openapi/`、`samples/webapi/`：真实响应样例
- `gps51_probe2.py`：探测脚本，`python3 gps51_probe2.py http://api.gps51.com/openapi <outdir>`
