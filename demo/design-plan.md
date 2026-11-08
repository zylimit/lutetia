# Ariane · Copper Watch 设计稿 · 设计计划（两遍法）

> 2026-11-08 · 依据 Product-Spec.md v1.13、Design-Brief.md、DESIGN.md（2026-11-08）· 取代 2026-11-07 的「拆除作战室」Demo 计划（深海军蓝 + 铜色、总览以拆除计划开头；在 Brief 之前出，方向已被 DESIGN.md 取代，旧稿留在 git 历史 27d0c0f）
> 生成路：fra 上的 Open Design（odc 0.25.1，daemon 127.0.0.1:17456，`OD_DAEMON_URL`），skill `frontend-design`，design system 基底 `ibm`（用 Plex、灰阶工程感，最接近 DESIGN.md）；token 以 DESIGN.md 为准、在 prompt 里声明覆盖基底。
> 方向已拍板（DESIGN.md + 用户 2026-11-08 逐项选择），跳过三方向样张，直接出全稿。
> 数据：全部合成——IMEI 用 8643170875901NN 合成段，GPS 设备号沿用 Spec 已公开的 4072400634 等 5 台，工单号用 6000xx 合成段，市镇用公开地名，不含真实重量、日期、地址或分包商明细。

## 1. token 摘录（来自 DESIGN.md）
| 角色 | 深色 | 浅色（嵌入 / 投影） | 用途 |
|---|---|---|---|
| neutral / surface / raised | #15181C / #1C2025 / #252A31 | #F5F6F8 / #FFFFFF / #F0F2F5 | 三级明度分层，不用阴影 |
| on-surface / muted / secondary | #E8EBEF / #A2AAB5 / #7E8792 | #171B20 / #4E5661 / #6A727D | 正文 / 次级 / 元信息与边 |
| border | #343B44 | #D3D8DF | 发丝线 |
| warning（24 h 内被动过） | #F0A73A | #A65A00 | 琥珀 + 三角 |
| error（正在挪动 / 错误） | #F26B66 | #B3261E | 红 + 实心三角 |
| offline | #7E8792 | #6A727D | 灰 + 空心斜线圆（图标用；文字用 muted） |
| primary（唯一主按钮） | #E8EBEF on #15181C | #171B20 on #FFFFFF | 登录、导出 |
字族：IBM Plex Sans（全部阅读文字，表格数字用 tabular-nums）+ IBM Plex Mono（只给 IMEI、工单号、事件时间）；产物离线，字体栈回退 `"IBM Plex Sans", system-ui, sans-serif`。圆角 4 / 6 / 8；间距 4 步进。

## 2. 线框

SCREEN-1 Overview（PC 1440）
```
┌ Ariane · Copper Watch   [Overview][Manholes][Bundles][Plan]   As of 08:42 CET  ◐  EN|FR  orange ▾ ┐
├──────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ SECURITY STATUS (CMP-1)                                                                              │
│  ▲ 1  moved in last 24 h     ⊘ 2  offline     ● 9  online                       as of 08:42 CET      │
├───────────────────────────────────────────────┬──────────────────────────────────────────────────────┤
│ Latest movement events (CMP-4 ×3)             │  Map (CMP-3 compact)                                 │
│ ▲ 864317087590107  Sun 8 Nov 02:14:07 CET     │   ● ● ▲ ● ⊘ ...  12 manholes                         │
│   6 min · 9 flips · Notified —                │                                                      │
├───────────────────────────────────────────────┴──────────────────────────────────────────────────────┤
│ Copper bundles: 5 trackers · 0 online · last position Wed 14 Oct 11:43 CET          → Bundles        │
├──────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Removal plan: 117 work orders · 25 with cable detail · 244.4 t planned (weight pending for 92)       │
│ Excel snapshot, as of 8 Nov 05:12 · Ariane is the source of truth                    → Plan          │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```
左对齐；状态带三项等宽列；只有「▲ 1」带琥珀。全部安静态：状态带换成一句「All 12 manholes quiet since Sun 8 Nov 02:20 CET」。
（注：上框里「SECURITY STATUS」只是线框标注，产物里标题用句首大写「Security status」，不做全大写眉标。）

SCREEN-2 Manholes（PC）
```
┌ nav ─────────────────────────────────────────────────────────────── [24 h | 7 d | 30 d] ┐
├────────────────────────────────────────────────────────────┬────────────────────────────┤
│ Map (≈2/3)  ● normal  ▲ moved  ▲■ moving  ⊘ offline         │ Movement events (newest)   │
│  markers with "unverified" corner mark                     │ ▲ 864…0107 02:14:07 · 6 min│
│                                                            │ ▲ 864…0103 Sat 23:51 · 2 min│
│                                                            │ …                          │
└────────────────────────────────────────────────────────────┴────────────────────────────┘
                                         ┌ Drawer (CMP-6) ───────────────┐
                                         │ 864317087590107 · ▲ Moved      │
                                         │ Location unverified           │
                                         │ Volt 3.58 V · RSRP −97 dBm    │
                                         │ [7 d|30 d] line charts        │
                                         │ Events for this manhole        │
                                         └───────────────────────────────┘
```

SCREEN-3 Bundles：同 SCREEN-2 骨架，右侧是设备列表（CMP-7）；顶部一句「Shows last position and 7-day track only; trip status is not computed yet」。

SCREEN-4 Plan
```
Source note (CMP-10)
Filters: [UCI ▾][Subcontractor ▾][Commune ▾][Category ▾][Underground/Aerial ▾][Cable type ▾]  Clear filters
┌ Planned tonnes by subcontractor ┐ ┌ Planned tonnes by cable type ┐   (covers 25 of 117 work orders)
Work orders table (CMP-9): POI · UCI · Subcontractor · Commune · Category · Segments · km · t · Received · Planned op · OCC [Open in Ariane]
  ▸ expandable segments
SLA reference (by category) — "Reference only — not tracked per work order"
```

SCREEN-5 Sign in：居中窄表单，项目名在上，「Keep me signed in for 30 days」，语言切换在下。

SCREEN-E1 / E2 / E3（浅色、无导航，宽 360 – 720）：时间线 / 地图 / 一行状态带；未登录态 CMP-11。

手机（390）：底部标签 Overview / Manholes / Bundles / Plan；Manholes 地图上半屏、事件列表下半屏；抽屉改全屏底部弹层；Plan 表格改紧凑行。

## 3. 大胆一处 / 动效一处
- 大胆：出事的那口井盖——地图标记琥珀三角 + 事件条琥珀左边与图标；其余全是灰阶。
- 动效：新事件到达时该标记脉冲三次（600 ms × 3）后停住；reduced-motion 下不脉冲。原型里用演示面板的「Simulate new movement event」触发。

## 4. 组件复用
CMP-1 状态带（SCREEN-1、E3）· CMP-3 地图（1、2、3、E2）· CMP-4 事件条（1、2、E1）· CMP-5 范围切换 · CMP-6 抽屉 · CMP-7 设备列表（2、3）· CMP-8 筛选 · CMP-9 表格 · CMP-10 来源标注 · CMP-11 嵌入登录提示 · CMP-12 提示条。

## 5. 原型说明（模拟边界）
- 全部数据写死在页面里，不请求任何后端；刷新回到初始态。
- 右下角「Prototype controls」面板（只在原型里有，不是产品功能）：切账号（orange / huawei / admin）、切主题（深 / 浅 / 投影）、切语言（EN / FR）、切状态（正常 / 全部安静 / 加载 / 离线 / 数据滞后 / 错误 / 未登录）、触发新挪动事件、切嵌入视图、Reset prototype。
- 「Export filtered rows (CSV)」真的在浏览器里生成文件，只含合成数据；登录不校验密码（演示）。
- 「Open in Ariane」只显示提示「Opens Ariane planning board (not linked in prototype)」，不跳转。

## 6. 第二遍自审（对照 style-vocabulary AI 通病与 DESIGN.md Don'ts）
| 原本（第一遍或旧 Demo） | 改成 | 为什么 |
|---|---|---|
| 旧 Demo 深海军蓝 + 铜色强调 | 石墨灰阶，无强调色 | DESIGN.md：颜色只留给状态；铜色会与琥珀告警混淆 |
| 旧 Demo 首屏「法国示意图 + 大数字吨数」 | 首屏是防盗状态带 + 最新事件 + 地图 | 用户 2026-11-08：首要用途是防盗；吨数退到最下 |
| 线框里「SECURITY STATUS」全大写标题 | 句首大写「Security status」 | 通病：全大写眉标 |
| 元信息用「6 min · 9 flips · Notified —」中点串 | 保留在事件条内，但用间距与竖排对齐代替中点，PC 用三列 | 通病：中点串元信息 |
| 「→ Bundles」「→ Plan」链接尾箭头 | 改成文字链接「View bundles」「Open plan」 | 通病：按钮 / 链接尾巴箭头 |
| 各块进场淡入上滑 | 不做；只有新事件脉冲 | DESIGN.md Motion：只留一处 |
| 在线设备用绿色点 | 中性实心圆 | DP-1 平静直到出事 |
| 面板一律同圆角同灰影 | 面板 6 px、控件 4 px、无阴影，靠明度分层 | 通病：SaaS 卡片套件 |

## 7. 覆盖矩阵（页面 × 状态 × 任务）
| 页面 | 默认 | 空 | 加载 | 错误 | 离线 | 数据滞后 | 无权限 | 任务 / 验收锚点 |
|---|---|---|---|---|---|---|---|---|
| SCREEN-1 | ✓ | 全部安静 | ✓ | ✓ | ✓ | ✓ | 跳登录 | FLOW-4：一眼看出被动过、点进去 |
| SCREEN-2 | ✓ | 范围内无事件 | ✓ | ✓ | ✓ | ✓ | 跳登录 | 找到 02:14 那口井盖、打开抽屉 |
| SCREEN-3 | ✓ | 24 h 无上报（当前生产即是） | ✓ | ✓ | ✓ | ✓ | 跳登录 | 看最后位置与轨迹 |
| SCREEN-4 | ✓ | 筛选无结果 | ✓ | ✓ | ✓ | — | 跳登录 | 筛选、展开、导出 |
| SCREEN-5 | ✓ | — | — | 密码错 | 离线 | — | — | 登录 |
| E1 – E3 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | CMP-11 | 宿主里看事件 |
冲突、AI 工作中：不适用（只读、无 AI）。
未知（不阻塞）：通知渠道（只显示「Notified —」）、运输异常规则（Bundles 只给位置与轨迹）、井盖真实坐标（标 unverified）。

## 8. 生成结果与验收（2026-11-09）
- 生成：fra 上 odc 0.25.1，项目 52833a68，Agent Codex；首个 run 4331c5c5 只出计划未写文件（od-next-strategy 先计划后构建，状态 succeeded 但 artifactCount 0），同会话自动接续的 run df66b5ea 出稿，exit 0、1 个产物。
- 产物 demo/index.html 约 305 KB，其中约 239 KB 是内嵌的 IBM Plex 三个字重（SIL OFL 1.1，页内注明来源）——偏离了 prompt 的「系统字体回退」，但零外部请求、字形与 DESIGN.md 一致，保留。
- 手工改两处：① 状态带计数改为从 12 口井盖的状态现算（原写死「1 moved · 9 online」，是本计划线框的笔误，与地图和事件条的 2 被动过 + 1 正在挪动对不上；现为 3 / 2 / 7，合计 12）；② 删除 Open Design 注入样式里的一行中文注释。
- 结构：</html> 收尾、style / script 各一对配平；页面里中文 0 行。
- 离线：无 script src / link / @import / fetch；Playwright 实测加载与走查全程外部请求 0、控制台错误 0。
- token：hex 共 20 个，全部在 DESIGN.md 里；无 rgb() / hsl() / 渐变；box-shadow 只用作 inset 边线，无投影；圆角 3 档。
- UI 审计（fra 上 Playwright Chromium，light / dark × 1280 / 390）：空白 0、溢出 0、对比度不足 0；rc 1 的唯一来源是「折行 ×4」——四个导航标签按顶栏通高 63 px 被判为折行，截图核对是单行，属启发式误报；中点分隔 ×4（标题、示意图注、来源标注、铜缆捆一句），不在事件条元信息里，保留。
- 任务试走（Agent 用 Playwright 自检，不是真人）：
  - 找到 02:14 被动过的井盖：总览事件条点 107 → 抽屉打开，含 IMEI 与「Location unverified」；Esc 关闭，焦点回到该事件条。
  - 拆除计划：6 个筛选，选分包商 Hovia → 10 行；导出 CSV 真下载，11 行（表头 + 10）。
  - 七种状态（正常 / 全部安静 / 加载 / 离线 / 数据滞后 / 错误 / 未登录）逐个切换都有对应呈现；FR 下标签为 Vue d’ensemble / Regards / Tourets / Plan。
  - reduced-motion 下模拟新事件：跳到 Manholes，脉冲动画 none。
  - 键盘：前 8 个 Tab 停点焦点环均可见。
- 未验证：真人试走；投影仪上的可读性；Safari / iOS 实机；法语措辞「Tourets」（DQ-4，待法语使用者确认）。
