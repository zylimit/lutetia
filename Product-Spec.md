# Product Spec：Lutetia 巴黎项目 IoT 数据采集服务

版本 v1.1 · 2026-11-06 · v1.0 同日由 TASK.md（2026-11-06 版）转写，自 v1.0 起 TASK.md 退役，本文档是唯一需求来源；v1.1 按首版代码审查与本地实测修订（见 CHANGELOG）。
来源标记：`[确认]` 用户确认的事实（TASK.md 原文 / docs/vendor 调研记录 / 现有代码）、`[推断]` AI 的推断、`[默认]` AI 采用的低风险默认（用户可否决）、`[待定]` 只出现在文末问题表里。没标记的按推断对待。

## 0. AI 使用说明
- 本文档是产品功能、范围、行为和验收的事实来源；下游 AI（dev-planner / implementer / code-reviewer / tester）按它开工。
- 优先实现 P0；不实现「非目标」里明确排除的内容；按「成功判据」与功能条目的产出判断完成。
- 条目标 `[推断]` `[默认]` 的，实现时若现场证据相反，回报「需求存疑」并附反例，不自行改需求；`[待定]` 表里的按「不答先按什么做」做。
- 两家接口的字段、配额、实测坑和真实响应在 `docs/vendor/gps51/` 与 `docs/vendor/dingtek/`，实现前先看，不要再探测接口。

## 产品概述
- 这是什么：一个常驻 Python 服务，把 GPS51（途强物联 GPS）和 Dingtek Cloud（DC414 井盖传感器）两套第三方云的数据持续落到自己的 PostgreSQL，供后续分析 `[确认]`（来源：TASK.md 目标）。
- 为什么现在做：两套云都不保证数据保留。Dingtek 的 PDF 写「最多保留 1 个月」，2026-11-06 实测最早一条是 2026-08-21，已 77 天，但那是目标不是承诺，付费到期一周后可能删；GPS51 轨迹接口每设备每天只许查 5 次且明文禁止服务器自动同步。不自己落库，过期的数据就没了 `[确认]`（来源：docs/vendor/dingtek/README.md「保留与配额」、docs/vendor/gps51/README.md「配额」）。
- 谁受益：巴黎项目后续做分析的人，拿到的是一份不依赖厂家保留策略的完整存档 `[推断]`（来源：TASK.md「供后续分析」，具体分析需求未谈）。
- 谁买单：项目运维，要维护一台固定公网 IP 的云主机、把 IP 加进 GPS51 白名单、在 GPS51 后台配转发 `[确认]`（来源：TASK.md 目标、README 部署节）。
- 谁可能变差：GPS51 账号，采集服务一旦轮询失控会吃光每日配额、触发封 API，网页端同账号的人也会受影响 `[确认]`（来源：TASK.md 反直觉设计 1、2）。
- 核心价值：做成之后，不用再靠厂家平台留数据，也不用人工定期导出。
- 风险档位：内部 `[推断]`（来源：无对外用户、不涉钱；设备数据不直接关联个人，隐私问题见「非功能与隐含合规」）。

## 应用场景：工作现状故事

**案例 1：Dingtek 的数据只在厂家平台上**（来源：docs/vendor/dingtek/README.md 2026-11-06 调研，亲历）
2026-11-06，调研人用 CUSTOMER_USER 角色登录 cloud.dingtek.com，发现它就是一套 ThingsBoard。12 台 DC414 全在巴黎：7 月装的 2 台固件 4.3，8 月 17 日后离线；8 月 19 日装的 10 台固件 4.4 全部在线，最后上报 2026-11-05。拿 864317087586940 这台看近 7 天：每 61 分钟一个心跳点，偶发一次性补传 354 个点，7 天 826 点，frameCounter 跨度 833，丢 7 帧。要看历史只能一台一台调 REST，没有自己的库，一个月前的数据能不能查全凭厂家心情。

**案例 2：GPS51 的配额一天就能用完**（来源：docs/vendor/gps51/README.md 2026-11-06 调研，亲历）
GPS51 账号 usertype=2、multilogin=1，5 台设备里只有 4072400634 和 4072400915 两台在巴黎正常，另外 3 台过期或从未上线。每日配额 1440 次加设备数乘 5，lastposition 1 次/分钟就是 1440 次，刚好吃满；querytracks 每设备每天 5 次、1 天 548 km 返回 928 条 758 KB。文档里写 speed 单位「米」，实测最大 122232 是米/小时。靠轮询拿实时位置这条路走不通，厂家后台的「数据转发」能把位置用 Http Json 推到我们的地址，不占配额，但当前账号 forwards 为空、还没配。

**例外**：GPS51 的 3 台非在线设备（4072401353 过期、4072407731 过期、4072407783 从未上线）仍会出现在设备列表里，同步设备时照样入库，但不算「应在线」，失联告警不管它们 `[确认]`（来源：README 设备表 + parsers/gps51.py 以 isfree==1 判应在线）。

## 成功判据
| 编号 | 判据（可数、技术无关） | 当前基线 | 目标 | 反向指标（看住副作用） | 来源 |
|------|------------------------|----------|------|------------------------|------|
| SC-1 | 执行一次 Dingtek 回补（从 2026-08-21 起）后，有遥测数据的设备数 | 本机库 2026-11-05 跑过首轮：141,545 行遥测、12 台里 10 台有 REST 行；2026-11-06 同区间复跑实测 12 台全部 0 新增、末行 inserted rows: 0。生产库仍为 0 | ≥ 10 台；**立刻再跑一次，新增行数为 0** | 重复行数 = 0 | `[确认]` TASK.md 验收 1 |
| SC-2 | 常驻运行 2 小时，10 台在线 Dingtek 设备各自新增行数 | 0 | 每台 ≥ 1 行，且 volt / temperature 最新值与厂家 REST 最新值一致 | Dingtek 登录次数 24 小时 ≤ 1 | `[确认]` TASK.md 验收 2、5 |
| SC-3 | 按厂家转发格式手工 POST 一条位置到接收端 | 2026-11-06 本机实测通过：10 ms 返回 200、5 秒内落库、重复投递 0 新增、空体与非法 JSON 均 400 | 100 ms 内返回 200；5 秒内 gps_position 出现该行；同一条再 POST 一次行数不变 | 接收端被非法 JSON 打挂次数 = 0 | `[确认]` TASK.md 验收 3 |
| SC-4 | 推送静默 15 分钟后自动切轮询 | 无 | 日志出现切换记录；lastposition 返回的 4 条记录落库；24 小时内 GPS51 总调用 ≤ 1450 次 | 24 小时 GPS51 登录 ≤ 2 次；querytracks 自动调用 = 0 | `[确认]` TASK.md 验收 4、5 |
| SC-5 | 巡检命令给出每个数据源每台设备的最后入库时间 | 无 | 任一应在线设备超过 3 小时无新数据时退出码非 0 | 非在线设备不触发告警 | `[确认]` TASK.md 验收 6 |
| SC-6 | 解析层单元测试用 samples/ 里的真实 JSON 做输入 | 2026-11-06 本地 46 条全绿（首版 18 条 + 审查回归 24 条 + 3.9 兼容与密码前缀机器闸 4 条）；python:3.9-slim 容器里解析器与兼容用例也绿 | 覆盖 GPS 推送 + 轮询两条路径、Dingtek 属性 / 遥测 / 历史三种响应；全仓搜不到两家账号密码的前缀（`Huawei` 紧跟 `@`、`liwei` 紧跟 `@`；模式不写成字面量，免得本文档自匹配） | 代码、日志、测试里出现密码或 token 的次数 = 0 | `[确认]` TASK.md 验收 7 + 本地 pytest |

## 范围与非目标
**本版范围**（每条 P0 单独实现也是可用的一小步）
| 编号 | 内容 | 优先级 | 来源 |
|------|------|--------|------|
| SCOPE-1 | 建表命令：五张表、两个换算视图，幂等 | P0 | `[确认]` README 命令表 |
| SCOPE-2 | Dingtek REST 全量回补（首次从 2026-08-21）与每日回补 | P0 | `[确认]` TASK.md 数据源表 |
| SCOPE-3 | GPS51 推送接收端（主通道）+ 静默 15 分钟后 lastposition 轮询（兜底） | P0 | `[确认]` TASK.md 数据源表、反直觉设计 2 |
| SCOPE-4 | Dingtek WebSocket 实时订阅（主通道） | P0 | `[确认]` TASK.md 数据源表 |
| SCOPE-5 | 两源设备同步与幂等落库（所有写入路径 upsert） | P0 | `[确认]` TASK.md 反直觉设计 8 |
| SCOPE-6 | 凭据会话复用与配额守护（GPS51 23 小时登一次 + 日预算；Dingtek JWT 续期 + 登录退避） | P0 | `[确认]` TASK.md 反直觉设计 4、5 |
| SCOPE-7 | 巡检命令 status（最后入库时间 + 退出码） | P1 | `[确认]` TASK.md 验收 6 |
| SCOPE-8 | GPS51 手工命令：同步设备、单次轮询、单次历史轨迹 | P1 | `[确认]` README 命令表、反直觉设计 1 |
| SCOPE-9 | 健康端点 GET /health 与日志里的调用计数 | P1 | `[确认]` README 部署节、TASK.md 验收 4 |
| SCOPE-10 | Docker 镜像 + docker compose（PostgreSQL 16 + 采集容器） | P1 | `[确认]` README 部署节 |

**非目标**（本轮明确不做）
| 编号 | 内容 | 原因 |
|------|------|------|
| OUT-1 | 任何分析、看盘、报表、Web 界面 | 地基阶段，数据还没攒起来；分析需求未谈 |
| OUT-2 | 在落库时做单位换算（速度、电压、信号） | 换算系数部分未经厂家确认，存原始值，换算只在视图层 |
| OUT-3 | 服务器自动同步 GPS51 历史轨迹（querytracks） | 厂家明文禁止，违反会被封 API |
| OUT-4 | 向设备下发任何指令、改围栏、改转发配置、改白名单 | 只读采集；转发与白名单由人在 GPS51 后台操作 |
| OUT-5 | 失联、报警的主动通知（短信 / IM） | 本版只给 status 退出码，交给外部监控接 |
| OUT-6 | 推送接收端的鉴权与 HTTPS 终结 | 见问题表第 4 行，先按明文 8080 + 反代建议 |

**以后**（可能做，本轮不依赖）
- 看盘 / 报表：等 SC-1、SC-2 稳定跑过一个月再谈。
- Dingtek 报警记录（/api/alarm）入库：目前 12 台 0 条报警，没有样例。
- GPS51 报表类接口（日里程、行程、停留）入库：占配额，需要先看推送通道稳定后的配额余量。
- 外部监控接 /health 与 status 退出码做告警。

## 功能需求
每条：用户做什么 → 系统做什么 → 得到什么。命令名以代码为准是 `lutetia`（TASK.md 写的 `collector` 已过时，见澄清记录）。

**核心功能**
- 建表：运维执行 `lutetia migrate` → 系统按 sql/ 目录顺序执行建表脚本，全部 IF NOT EXISTS → device / gps_position / sensor_telemetry / sensor_attribute / api_call 五张表与 gps_position_v / sensor_telemetry_v 两个视图就绪，重复执行不报错 `[确认]`（来源：README 命令表、sql/001_schema.sql）
- Dingtek 全量回补：运维执行 `lutetia backfill dingtek --from 2026-08-21`（可选 `--to`）→ 系统同步设备列表，对每台设备按天分窗拉 values/timeseries，单窗某个 key 撞到 1000 条上限就对半切窗重拉（最小窗 15 分钟），全部 upsert，顺手刷新属性与 active 标记；某台设备出错（HTTP 错误、超时、返回非 JSON）不中止整批，记入失败清单继续下一台 → 打印新增行数，有失败时再逐台打印 FAILED 行并以退出码 1 结束；第二次执行同一区间新增为 0 `[确认]`（来源：TASK.md 验收 1；失败隔离为 2026-11-06 审查 M-6 / N-4 修复；幂等 2026-11-06 本机实测）
- GPS51 推送接收：GPS51 后台把位置以 Http Json 转发到 `POST /gps51/push` → 系统解析 JSON 成功即入后台队列并立刻返回 200，队列消费者统一字段后 upsert 到 gps_position；写库遇连接类故障（库重启、连接断、超时）在内存里退避重试（1 秒起翻倍、封顶 30 秒）直到成功，不丢；一批里某行是数据类错误（越界值、非法字符）只丢那一行并写 warning，其余行照存；合法 JSON 但认不出位置的计 unrecognised；请求体为空或不是合法 JSON 返回 400 并计 rejected；进程收到 SIGTERM 先停收新请求、给队列最多 30 秒写完再退出 → 推送一条 100 ms 内收到 200，5 秒内库里有这一行，重复投递不产生新行 `[确认]`（来源：TASK.md 反直觉设计 3、验收 3；重试 / 丢行 / 停机清队列为 2026-11-06 审查 H-2 / H-3 / N-1 修复，本机实测）
- 推送静默切轮询：推送通道连续 15 分钟没有任何消息 → 系统写一条切换日志，开始每 60 秒调一次 lastposition（带上次返回的 lastquerypositiontime 做增量），推送一恢复就停 → 静默期间位置不断档，日志里能看到每次请求的累计计数 `[确认]`（来源：TASK.md 反直觉设计 2、验收 4、sources/gps51.py fallback_loop）
- Dingtek 实时订阅：常驻服务启动 → 系统用缓存 JWT 连 `/api/ws/plugins/telemetry`，对库里每台 Dingtek 设备订阅 LATEST_TELEMETRY，收到的每个 key 每个点 upsert；断线按 5 秒起指数退避重连（上限 120 秒），会话撑满 60 秒才把退避归零，连上就断的不归零；重连不重新登录，只在 JWT 被拒（errorCode=3 或握手 401 / 403）时续期，且刚拿到 token 120 秒内再被拒不重新登录、只按退避等待；任何日志行不含 token → 10 台在线设备每小时至少各来 1 行 `[确认]`（来源：TASK.md 数据源表、反直觉设计 5；退避与新 token 保护为 2026-11-06 审查 M-4 / N-3 修复，日志脱敏为 H-1 修复）
- Dingtek 每日回补：每天 03:00 UTC → 系统用 REST 重拉最近 2 天的遥测补 WebSocket 漏掉的点，并刷新属性与 active 标记 → WebSocket 回放、断线造成的空洞被填上，不产生重复行 `[确认]`（来源：TASK.md 数据源表「REST 每日回补」；回补窗口 2 天与 03:00 UTC 为代码现状，见决策依据）
- 设备同步：常驻服务启动或运维执行 `lutetia gps51 sync-devices` → 系统拉 GPS51 querymonitorlist 与 Dingtek /api/user/devices，两源混进 device 表靠 source 区分，整条原始设备记录塞进 extra，GPS51 以 isfree==1、Dingtek 以属性 active 判「应在线」 → device 表里 5 台 GPS + 12 台 DC414，各带应在线标记 `[确认]`（来源：TASK.md 数据结构 device、README 设备表）
- 幂等落库：任何路径（推送 / 轮询 / 历史轨迹 / WebSocket / REST 回补）写入 → 系统按去重键 upsert：GPS 位置 (device_id, update_time)，Dingtek 遥测 (device_id, key, ts)，属性整表覆盖 → 同一条数据从几条路来都只有一行 `[确认]`（来源：TASK.md 反直觉设计 8）
- GPS51 会话与配额守护：任何 GPS51 调用前 → 系统复用 state/ 里存盘的 token（24 小时有效，满 23 小时才重新登录；9903 / 9906 被拒时重登一次），每次调用前查 api_call 表 24 小时内已用次数，到日预算（默认 1400）就拒绝并暂停轮询 1 小时，相邻调用间隔不少于 6 秒，8902 被限频时等 60 秒重试一次；请求超时或网络错误也计一次失败调用；登录失败后按 60 秒 × 2^(n-1) 退避、封顶 1 小时，退避期内不发登录请求（服务先起、白名单后加的那段时间不会把预算烧在 login 上）；轮询游标在本批入库成功后才推进 → 24 小时登录 ≤ 2 次、总调用 ≤ 1450 次，不会触发 8905 `[确认]`（来源：TASK.md 反直觉设计 4、验收 4、5；超时计数、登录退避、游标规则为 2026-11-06 审查 M-3 / M-2 / H-4 修复）
- Dingtek 会话守护：任何 Dingtek 调用前 → 系统复用存盘的 JWT，到期前 5 分钟内用 refreshToken 续，续不了才登录；登录间隔不少于 15 秒，连续失败按 15 秒 × 2^n 退避（上限 15 分钟）；401 续期后重试一次，429 等 30 秒重试一次 → 24 小时登录 ≤ 1 次，不会撞上每分钟每 IP 5 次的限制 `[确认]`（来源：TASK.md 反直觉设计 5、sources/dingtek.py DingtekClient）
- 原始值入库：解析任一数据源 → 系统把数值原样存（GPS51 speed 存米/小时，Dingtek volt 存 360、rsrp 存 -670），每条 GPS 位置的原始 JSON 存 raw 列，FSM 这类字符串遥测存 value_str → 换算只在 gps_position_v / sensor_telemetry_v 视图里做，换算错了改视图不动数据 `[确认]`（来源：TASK.md 反直觉设计 7）
- 哨兵值清洗：解析 GPS51 温度字段 → 系统把轨迹里的 65535 和最后位置里的 536870911 写成 NULL → 库里没有假温度 `[确认]`（来源：TASK.md 数据结构「温度哨兵值」、parsers/gps51.py TEMP_SENTINELS）

**辅助功能**
- 巡检：运维执行 `lutetia status`（可选 `--max-age-hours`，默认 3） → 系统列出每个数据源每台设备的名字、类型、应在线标记、最后入库时间，以及最近 24 小时各接口调用次数；应在线设备的允许静默时长取 3 小时与「2 倍 uploadInterval」中的大者 → 有失联设备时标 STALE 并退出码 1，否则 0 `[确认]`（来源：TASK.md 验收 6；2 倍 uploadInterval 规则为代码现状 `[推断]` 来自 cli.py cmd_status）
- 手工历史轨迹：运维执行 `lutetia gps51 tracks --device ID --begin '2026-10-06 00:00:00' --end '2026-10-06 23:59:59'`（UTC+8） → 系统调一次 querytracks 并 upsert → 补一天的轨迹；没有任何自动触发路径，每设备每天 5 次由人自己数 `[确认]`（来源：TASK.md 反直觉设计 1、README 命令表）
- 手工单次轮询：运维执行 `lutetia gps51 poll-once` → 系统调一次 lastposition 并 upsert → 打印新增条数 `[确认]`（来源：README 命令表）
- 健康端点：监控系统 GET /health → 系统返回 received（收到并入队）/ stored（已写库新行）/ rejected（400 拒绝）/ unrecognised（合法 JSON 但认不出）/ failed（非数据库类异常丢弃）/ queued（队列待写）计数与推送静默秒数 silent_sec → 外部监控能判断接收端活着、在收数据，以及第一条真实推送有没有被认出来 `[确认]`（来源：README 部署节；unrecognised / failed 为 2026-11-06 Task 1.3 新增）
- 换算视图：分析者查 gps_position_v / sensor_telemetry_v → 系统给出 speed_kmh、total_distance_km、temp1_c 与 value_si（volt ÷ 100、rsrp ÷ 10，其余原值） → 不碰原始表就能拿到工程单位 `[默认]`（来源：sql/001_schema.sql；volt / rsrp 系数未经厂家确认，见问题表第 1 行）
- 调用计数：每次调第三方接口 → 系统往 api_call 表记一行（源、action、是否成功、时间） → 日志与 status 里能看到累计次数，配额守护也从这张表读 `[确认]`（来源：TASK.md 验收 4「累计计数」、db.py record_api_call）
- 容器部署：运维执行 `docker compose up -d --build` → 系统起 postgres:16-alpine 与采集容器，容器启动先 migrate 再 run，状态目录挂卷，8080 映射给推送 → 一条命令起全套 `[确认]`（来源：README 部署节、Dockerfile、docker-compose.yml）

## 规则与例外
| 规则 | 例子 | 例外 | 来源 |
|------|------|------|------|
| GPS51 绝不自动循环调 querytracks | 2026-10-06 查 4072400634 一天轨迹是人手敲命令拿到的 928 条 | 无。连每日回补也不走它 | `[确认]` TASK.md 反直觉设计 1、docs/vendor/gps51/README.md |
| 推送是 GPS51 主通道，轮询只在推送静默 15 分钟后启用，推送恢复即停 | 账号配额 1440 + 5 × 5，1 次/分钟轮询正好吃光 | 推送从未配好（forwards 为空）时，服务启动后 15 分钟进入轮询并一直轮询，直到人在后台配好转发 | `[确认]` TASK.md 反直觉设计 2 |
| 推送接收端收到即 200，写库在后台 | 厂家对非 200 的重试行为未知 | 请求体为空或不是合法 JSON 时返回 400 不入队；写库失败不丢：连接类故障退避重试到成功，数据类错误只丢那一行并计数；停机给队列最多 30 秒写完 | `[确认]` TASK.md 反直觉设计 3；400 与重试分支为 2026-11-06 审查修复后的代码现状，本机实测 |
| GPS51 每 23 小时登录一次，token 存盘复用 | 登录也计配额；multilogin=1，脚本登录不踢网页会话 | token 被 9903 / 9906 拒绝时立刻重登，不等 23 小时 | `[确认]` TASK.md 反直觉设计 4 |
| Dingtek 登录每分钟每 IP 5 次，JWT 存盘、到期用 refreshToken 续 | 调研时登录限频是厂家唯一给了数字的限制 | WebSocket 断线重连不重新登录；只有 refresh 也失败才登录 | `[确认]` TASK.md 反直觉设计 5 |
| Dingtek 设备主键用 ThingsBoard UUID，name / label 存 IMEI | 864317087586940 的 UUID 是 79702a70-9ba1-11f1-898a-012e63463e84，接口一律要 UUID | 无 | `[确认]` TASK.md 反直觉设计 6 |
| 数值存原始值，换算在视图 | speed 文档写米、实测米/小时；volt ×0.01 V、rsrp ×0.1 dBm 是推测 | 温度哨兵值 65535 / 536870911 不原样存，写 NULL | `[确认]` TASK.md 反直觉设计 7、数据结构 |
| 所有写入路径 upsert，去重键决定幂等 | 推送重复投递、WebSocket 重连回放、REST 回补与实时重叠 | 属性表不是追加而是整表覆盖，取最后一次的值 | `[确认]` TASK.md 反直觉设计 8、数据结构 sensor_attribute |
| 遥测用窄表（key 一行），不按 key 建列 | 固件 4.3 有 angle，4.4 没有 | 无 | `[确认]` TASK.md 数据结构 sensor_telemetry |
| 三个时间都存：device_time（设备 GPS 时间）、arrived_time（到厂家服务器）、update_time（排序与去重） | 推送字段是 lat / lon，接口是 callat / callon，落库前统一 | 推送缺 updatetime 时退而用 arrivedtime 当去重键；两者都缺这条丢弃 | `[确认]` TASK.md 数据结构 gps_position；退化规则为代码现状 `[推断]` |
| 时间戳全是 UTC 毫秒，库里统一 timestamptz | 两家接口都是毫秒 | querytracks 的查询参数用 `yyyy-MM-dd HH:mm:ss` + timezone=8，只有这个入口是北京时间 | `[确认]` TASK.md 数据结构、docs/vendor/gps51/README.md 实测坑 |
| 应在线设备 3 小时无新数据算失联 | 10 台 DC414 每 61 分钟一个心跳 | uploadInterval 大于 1.5 小时的设备，允许静默 2 倍 uploadInterval | `[确认]` TASK.md 验收 6；2 倍规则 `[推断]` 代码现状 |
| 调试期对真实接口的调用有上限 | GPS51 每次运行总数 ≤ 20 次、间隔 ≥ 2 秒；Dingtek 只在 token 文件不存在时登录一次 | 无 | `[确认]` TASK.md Agent 约束 |
| 凭据只从环境变量读；代码、日志、测试里不出现密码或 token | GPS51_USER / GPS51_PWD、DINGTEK_USER / DINGTEK_PWD、DATABASE_URL | 本地 .env 文件可以放，已 gitignore | `[确认]` TASK.md 必读资料、Agent 约束 |

## 关键流程

**FLOW-1：首次上线与回补**（关联：SCOPE-1、2、5、6、10）
主角：项目运维小雷（化名）。
1. 小雷在固定公网 IP 的云主机上 `docker compose up -d --build`，采集容器先 migrate 建表，再以 run 常驻。
2. 他执行 `docker compose exec collector lutetia backfill dingtek --from 2026-08-21`，日志逐台打出「backfill 864317087586940 (79702a70…): N new rows, active=True」。
3. 他立刻再执行一次同样的命令，日志里每台都是 0 new rows，末行 inserted rows: 0、退出码 0（哪台拉失败了，inserted rows 之后会跟 FAILED 行、退出码 1，他只需重跑一次）。
4. 他跑 `lutetia status`，12 台 DC414 的最后入库时间都是 2026-11-05 之后，10 台 online 列是 yes，2 台固件 4.3 的是 no。
5. **高潮**：小雷把主机 IP 加进 GPS51 白名单、在后台「转发平台列表」填上 `http://主机IP:8080/gps51/push`，几分钟后日志出现「gps51 push: 1 positions, 1 new」。他不用再盯着厂家平台了。
**失败路径**：第 2 步 Dingtek 登录返回 401 → 日志「dingtek login rejected (401): check credentials」，进程退出码非 0，库里什么都没写 → 小雷改 .env 里的 DINGTEK_USER / DINGTEK_PWD 重跑；连续失败时登录间隔自动拉长，不会把账号打进限频。

**FLOW-2：常驻采集的一天**（关联：SCOPE-3、4、5、6、9）
1. 03:00 UTC，服务用 REST 重拉最近 2 天的 Dingtek 遥测，日志「dingtek reconcile: 7 rows added」，这 7 行是夜里 WebSocket 断线 20 秒漏掉的。
2. 09:12，GPS51 推送来了 4072400634 的位置，接收端 2 ms 返回 200，队列消费者 upsert 一行；厂家把同一条又推了一次，第二次 0 new。
3. 14:00 起 GPS51 转发服务器出故障，推送没了。14:15 日志「gps51 push silent for 15 min -> polling every 60s」，之后每分钟一次 lastposition，每次日志带本次返回条数与新增条数。
4. 15:40 推送恢复，下一轮检查发现静默时长归零，日志「gps51 push resumed -> polling stopped」。这 85 分钟用掉 85 次配额。
5. **高潮**：第二天小雷看 status 的「api calls last 24h」：gps51 lastposition 85、login 1，dingtek timeseries 24、login 0。两家都没碰到配额线。
**失败路径**：第 3 步轮询持续到当天用量碰到预算 1400 → 日志「gps51 daily budget reached: 1400/1400; polling paused for 1h」，1 小时后再试；推送接收端照常工作，已入库数据不受影响。

**FLOW-3：巡检发现设备失联**（关联：SCOPE-7）
1. 小雷的 cron 每小时跑一次 `lutetia status`。
2. 某次输出里 864317087586941 的 last_data_utc 停在 5 小时前，行尾标 STALE，末行「1 expected-online device(s) without recent data」，退出码 1。
3. **高潮**：cron 捕获非 0 退出码报给他，他去现场看井盖，而不是三天后在厂家平台上才发现数据断了。
**失败路径**：数据库连不上 → 命令直接抛连接异常、退出码非 0，没有「全部正常」的假输出。

## 数据与权限
| 实体 | 关键字段 | 谁能改（单一写入者） | 谁只看 | 删除 / 归档 | 来源 |
|------|----------|----------------------|--------|-------------|------|
| device | source、device_id（GPS51 用 deviceid，Dingtek 用 UUID）、name、device_type、expected_online、extra jsonb | 采集服务（设备同步时 upsert） | 分析者 | 不删；设备从厂家列表消失时本行保留 | `[确认]` TASK.md 数据结构 |
| gps_position | device_id、update_time、device_time、arrived_time、lat、lon、speed_raw、course、altitude、total_distance、status、alarm、strstatus、stralarm、moving、temp1-4、origin（push / poll / tracks）、raw jsonb | 采集服务（三条路径都 upsert） | 分析者（经 gps_position_v） | 不删，这是唯一可信存档 | `[确认]` TASK.md 数据结构、目标 |
| sensor_telemetry | device_id、key、ts、value_num、value_str、origin（ws / rest） | 采集服务 | 分析者（经 sensor_telemetry_v） | 不删 | `[确认]` TASK.md 数据结构 |
| sensor_attribute | device_id、key、value、last_update_ts | 采集服务（整表覆盖） | 分析者；status 读 uploadInterval | 覆盖即丢旧值，不留历史 | `[确认]` TASK.md 数据结构 |
| api_call | source、action、ok、called_at | 采集服务（每次外部调用追加） | status 命令、配额守护 | 本版不清理 `[默认]`（来源：表很小，每天最多两千行） | `[确认]` db.py |
| state/ 目录（gps51_token.json、dingtek_token.json） | token、serverid、refreshToken | 采集服务 | 无人 | 文件删掉就重新登录；已 gitignore、容器里挂卷 | `[确认]` TASK.md 反直觉设计 4、5 |

## 决策依据
| 决定 | 备选 | 为什么 | 谁定的 |
|------|------|--------|--------|
| GPS51 推送为主、轮询兜底，不做轨迹自动同步 | 纯轮询；定时 querytracks | 配额与封号风险，见反直觉设计 1、2 | 既定不可碰（TASK.md） |
| 接收端先 200 后写库 | 写完再 200 | 厂家重试行为未知，不能靠它重发 | 既定不可碰（TASK.md） |
| 存原始值，换算在视图 | 落库时换算 | 两个系数是推测，改视图比改数据便宜 | 既定不可碰（TASK.md） |
| Dingtek 主键用 UUID | 用 IMEI | 接口只认 UUID | 既定不可碰（TASK.md） |
| 去重键 (deviceid, updatetime) 与 (uuid, key, ts)，全路径 upsert | 追加 + 事后去重 | 推送重复、WS 回放、回补重叠三种重复都要挡在写入口 | 既定不可碰（TASK.md） |
| 命令名用 `lutetia`，不用 TASK.md 里的 `collector` | 改代码迁就 TASK.md | 代码、README、pyproject 入口都已是 lutetia；验收脚本以此为准 | AI 决定（转写时以代码为准），用户可否决 |
| 每日回补窗口取最近 2 天、03:00 UTC | 只补 1 天；按小时补 | 2 天能盖住跨午夜的断线；03:00 UTC 是巴黎凌晨，数据量最小。两者都是环境变量可调 | AI 建议、代码已采纳（`[推断]`） |
| GPS51 日预算默认 1400、调用间隔 6 秒 | 1440 满配额；按 10 次/分钟顶格 | 留 40 次给登录与手工命令；6 秒间隔即每分钟 10 次，正好是 IP 限频上限 | AI 建议、代码已采纳（`[推断]`） |
| status 失联阈值取 3 小时与 2 倍 uploadInterval 的大者 | 固定 3 小时 | 上报间隔长于 1.5 小时的设备按固定 3 小时会误报 | AI 建议、代码已采纳（`[推断]`） |
| 代码按 Python 3.9 兼容写，镜像用 python:3.12-slim | 只支持 3.12 | 目标服务器 Python 版本未确认 | 既定（TASK.md Agent 约束），版本问题见问题表 |
| 解析映射与单元测试用 haiku，采集主循环用 sonnet，不用 opus | 全程 sonnet / opus | 架构已定，拆得细的任务用便宜模型 | 既定（TASK.md 模型分配） |
| 框架脚手架目录 .claude/ 不入库 | 入库 | 与其他下游仓一致；未跟踪的 .claude/ 还会把档位误升 strict | 用户（2026-11-06） |
| TASK.md 退役，本文档取代 | 两份并存 | 用户要求转完就不用 TASK.md，避免两份口径 | 用户（2026-11-06） |
| 推送写库失败：连接类故障内存退避重试不丢、数据类错误丢单行并计数、停机给队列 30 秒 | 本地落盘缓冲；一切异常都无限重试 | 唯一存档不能丢；但一条毒行无限重试会卡死整条队列，落盘缓冲是下一版的事 | AI 建议、代码已采纳（2026-11-06 审查 H-2 / H-3 / F2b / N-1），用户可否决 |
| raw 列存 JSON 对象，不是 JSON 字符串；sql/002 幂等迁移修存量 4 行 | 存字符串、查询时再 cast | `raw->>'deviceid'` 这类查询要能直接用 | AI 决定（2026-11-06 审查 M-1），用户可否决 |
| 回补单台失败不中止整批，CLI 以退出码 1 报失败清单 | 任一台失败整批中止 | 每日回补被一台维护中的设备拖垮等于全部断档 | AI 决定（2026-11-06 审查 M-6），用户可否决 |

## UI 与使用情境
- 使用情境：没有图形界面。运维在终端或 `docker compose logs` 里看日志，cron 跑 status 看退出码，外部监控探 /health。
- 首要动作：`lutetia status` 一眼看到哪台设备断了。
- 布局与控件：无。日志每行带时间、级别、模块名；status 输出固定列宽表格，STALE 行有后缀标记 `[确认]`（来源：cli.py cmd_status、log.py）。

## 技术方向
| 维度 | 选择 | 理由 |
|------|------|------|
| 产品类型 | CLI + 常驻服务（Linux 容器） | 面向运维、批量、自动化，无人机交互 |
| 首版基准平台 | 固定公网 IP 的 Linux 云主机，Docker Compose | GPS51 白名单与推送地址都绑这个 IP `[确认]`（来源：TASK.md 目标） |
| 推荐技术栈 | Python ≥ 3.9（pyproject requires-python）、aiohttp ≥ 3.9（HTTP 客户端 + 推送接收端 + WebSocket）、asyncpg ≥ 0.29、pytest + pytest-asyncio | 代码现状。2026-11-06 核过 PyPI：asyncpg 0.32.0 要求 Python ≥ 3.9；aiohttp 3.14.5 要求 Python ≥ 3.10，目标机若真是 3.9，pip 会退到最后支持 3.9 的 aiohttp 3.1x，写法不受影响；本地开发 venv 是 3.14，容器是 3.12 |
| 数据存储 | 自有 PostgreSQL 16（compose 里 postgres:16-alpine，数据卷持久化） | 数据归项目，分析者要查，丢了等于厂家删了就没了 |
| 部署方式 | `docker compose up -d --build`；容器启动顺序 migrate → run；状态目录与数据库各挂一个卷 | 一条命令起全套；token 文件跨重启复用 |

## 非功能与隐含合规
| 类别 | 要求（数字或「不要求」） | 优先级 | 来源 |
|------|--------------------------|--------|------|
| 性能 | 推送 100 ms 内返回 200；入库延迟 ≤ 5 秒；回补吞吐不要求（按天分窗、撞 1000 条上限自动切半） | P0 | `[确认]` TASK.md 验收 3 |
| 安全 | 凭据只从环境变量读；仓库、日志、测试里 0 处密码或 token；GPS51 走 openapi 必须 IP 白名单；推送接收端本版不鉴权（建议：路径加随机段或校验共享密钥，谁知道地址谁就能往库里塞位置） | P0 | `[确认]` TASK.md Agent 约束；鉴权缺口为 AI 建议 |
| 隐私 | 本版按设备数据处理，不脱敏、不设保留上限；GPS 位置若能关联到具体驾驶人，在法国受 GDPR 约束，见问题表第 6 行 | P1 | `[推断]`（来源：设备在巴黎，GPS 装在「天禾充电设备」上） |
| 兼容 | Python 3.9 写法（无 match、无 `X \| Y` 类型联合、无 3.10+ 标准库）；PostgreSQL 16；Docker Compose v2 | P0 | `[确认]` TASK.md Agent 约束 |
| 可靠 | 24 小时 GPS51 调用 ≤ 1450、登录 ≤ 2；Dingtek 登录 ≤ 1；WebSocket 断线自动重连（5 秒起退避到 120 秒）；每日回补补洞；所有写入幂等；推送写库遇连接类故障重试不丢；进程收到 SIGTERM 后停收新请求、给队列最多 30 秒写完、取消任务、关闭接收端与连接池再退出（容器 stop_grace_period 要 ≥ 40 秒；进程被 SIGKILL 时队列里尚未写库的推送会丢，这是本版接受的残余风险） | P0 | `[确认]` TASK.md 验收 4、5；重试与退出流程为 2026-11-06 审查修复后的代码现状 |
| 可访问 | 不要求（无 UI） | 无 | `[确认]` |
| 行业隐含合规 | 只读采集，不向任何物理设备下发指令，不存在 fail-safe 问题；GDPR 适用与否交 DFX 定档 | P1 | `[推断]` |

## 待定问题
| 问题 | 影响什么 | 谁能答 | 押后到 | 不答先按什么做 |
|------|----------|--------|--------|----------------|
| Dingtek 的 volt 是不是 ×0.01 V、rsrp 是不是 ×0.1 dBm | sensor_telemetry_v 的换算；任何用电压 / 信号做的分析 | Dingtek 厂家（用户去问） | 第一次用换算值做分析之前 | 原始值照存，视图按 ÷100 与 ÷10 算，错了只改视图 |
| GPS51 推送收到非 200 会不会重试、重试几次 | 接收端要不要补偿机制；静默 15 分钟的阈值是否够 | 途强物联 | 上线后第一周看日志 | 收到即 200、后台队列落库，静默 15 分钟切轮询兜底 |
| 目标云主机的 Python 版本 | 依赖版本上限、能不能直接 pip 装还是只能走容器 | 用户 / 云主机运维 | 部署前 | 代码按 3.9 兼容写，部署走 python:3.12-slim 容器 |
| 推送接收端要不要 HTTPS 反代与鉴权 | GPS51 后台填的转发地址；伪造推送的风险 | 用户 | 在 GPS51 后台配转发之前 | 明文 http 8080、固定路径 /gps51/push、不鉴权 |
| GPS51 真实推送的 JSON 外层是单条、数组还是带 data 的信封 | parse_push_payload 的分支；SC-3 的手工测试用哪种形态 | 第一条真实推送（看日志里 unrecognised payload 有没有出现） | 收到第一条推送时 | 三种形态都接受，认不出的打 warning 并计数 |
| GPS 位置能否关联到可识别的个人（谁在开装了 GPS 的设备） | 是否要脱敏、是否要设保留期限、DFX 隐私档位 | 用户 / 巴黎项目合规负责人 | DFX 设计之前 | 按设备数据处理，不脱敏，永久保留 |
| 推送「静默」按什么算：任何合法 JSON 到达，还是真的入库了一条位置 | 若厂家只推心跳或报警、或任何人往接口 POST 一个 `{}`，现在都算「有消息」，静默计时归零，位置断了几小时也不会切轮询（2026-11-06 审查反例 1） | 用户 | Phase 2 本地长跑之前 | 按任何合法 JSON 算（代码现状）；/health 里 unrecognised 能看出有没有认不出的消息 |
| GPS51 报警转发消息（带 alarmtype 字段）要不要当位置入库 | 报警消息也带 deviceid / lat / lon / updatetime，现在会被存成 origin=push 的位置；若与真实位置同一 updatetime 且先到，真实位置那条会被去重丢掉（2026-11-06 审查反例 2，依据 docs/vendor/gps51/API/数据转发/转发报警消息.md 字段表） | 用户 | 在 GPS51 后台配转发之前 | 照现状入库（代码现状）；建议改为识别 alarmtype 后只计数不入库，报警入库留给「以后」 |

## 澄清记录
| 日期 | 问 | 答（来源） | 改了哪条 |
|------|----|-----------|---------|
| 2026-11-06 | 需求来源用什么 | 用户：把 TASK.md 转成 Product-Spec，之后不用 TASK.md | 全文；TASK.md 退役 |
| 2026-11-06 | 验收里的命令名 collector 还是 lutetia | 代码与 README 已是 lutetia（来源：pyproject [project.scripts]），未问用户 | 成功判据、功能需求、关键流程统一用 lutetia |
| 2026-11-06 | 风险档位 | 未问，按内部系统推断：无对外用户、不涉钱 | 产品概述「风险档位」 |
| 2026-11-06 | 每日回补窗口、预算、失联阈值这些数字从哪来 | 代码现状（config.py 默认值、cli.py、service.py），TASK.md 没写 | 功能需求与决策依据里标 `[推断]`，可用环境变量改 |
| 2026-11-06 | 脚手架目录要不要入库 | 用户：不提交 | 决策依据最后两行 |
| 2026-11-06 | 首版代码审查（code-reviewer 全三 Stage）发现 HIGH 4 条：JWT 进日志、推送写库失败丢行、停机丢队列、轮询游标先推进 | 修复并同轮复核通过（来源：DEV-PLAN Task 1.1，提交 060fd04）；未问用户 | 功能需求「GPS51 推送接收」「Dingtek 实时订阅」「GPS51 会话与配额守护」「Dingtek 全量回补」「健康端点」；规则与例外第 3 行；FLOW-1 第 3 步；非功能「可靠」；决策依据新增 3 行；SC-1 / SC-3 / SC-6 基线改实数 |
| 2026-11-06 | 审查提出 3 条「代码对得上 Spec、Spec 对不上业务」的反例 | 反例 3（200 后写库失败即丢）已由重试 + 停机清队列解决；反例 1（静默按什么算）与反例 2（报警转发当位置）进文末问题表，等用户答 | 文末问题表新增 2 行 |
