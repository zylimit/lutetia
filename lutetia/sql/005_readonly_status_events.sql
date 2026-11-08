-- Phase 7 Task 7.1：只读库角色 lutetia_ro、采集心跳表 collector_status、挪动事件视图 fall_event。
-- 每次启动 migrate 都会重跑，全部幂等。角色起建 NOLOGIN，登录密码由 migrate 末尾按 DATABASE_RO_PASSWORD 设置（不写在这里）。
-- 不改现有表；fall_event 是视图，无写入者（ADR-3）。

CREATE TABLE IF NOT EXISTS collector_status (
    id              smallint PRIMARY KEY CHECK (id = 1),   -- 单行表，写入方 upsert id = 1
    updated_at      timestamptz NOT NULL DEFAULT now(),    -- 心跳时间，写入方每次覆盖；看板按它判过期
    version         text,
    push_last_at    timestamptz,
    push_count_24h  int,
    ws_connected    boolean,
    polling         boolean,
    details         jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- 挪动事件：alarmFall 由 0 变非 0 的每次「翻转」按时间合并（SC-13）。规则只在这一处。
-- alarmFall 存法：Dingtek 数值（含 "0"/"1" 字符串）进 value_num，JSON 布尔进 value_str 'true'/'false'
-- （见 parsers/dingtek.py _telemetry）；两处都认，其余无法解析的行不参与。
--   翻转   = 非 0 行，且同设备按 ts 的前一行为 0 或不存在（上升沿）
--   事件   = 只有上升沿能开新事件：上升沿与同设备上一条非 0 记录相隔 > win（或没有上一条非 0）才开新事件，
--            否则并入当前事件；中间没有 0 的连续非 0（非上升沿）一律属于当前事件，不论间隔多长
--            （井盖挪开后一直歪着、每 61 分钟报一次心跳点，仍是一次挪动）
--   started_at = 事件第一条非 0 的 ts；ended_at = 事件最后一条非 0 之后该设备第一条 0 的 ts，没有则 NULL（仍在进行）
--   flips  = 事件内上升沿数（开事件的就是上升沿，故 >= 1）
--   事件两两不重叠：下一个事件由上升沿开启，其前一行必为 0 且晚于上一事件最后一条非 0，故上一事件的 ended_at 不晚于它的 started_at
CREATE OR REPLACE VIEW fall_event AS
WITH cfg AS (
    SELECT interval '30 minutes' AS win          -- SC-13 [默认] 合并窗口，改窗口只改这一行
),
base AS (
    SELECT device_id, ts, v <> 0 AS nz
    FROM (
        SELECT device_id, ts,
               COALESCE(value_num, CASE lower(value_str) WHEN 'true' THEN 1 WHEN 'false' THEN 0 END) AS v
        FROM sensor_telemetry
        WHERE key = 'alarmFall'
    ) s
    WHERE v IS NOT NULL
),
seq AS (
    SELECT device_id, ts, nz,
           lag(nz) OVER w AS prev_nz,
           count(*) FILTER (WHERE NOT nz) OVER w AS zeros_so_far   -- 到本行为止的 0 行个数；0 行自身即其序号
    FROM base
    WINDOW w AS (PARTITION BY device_id ORDER BY ts)
),
nzr AS (
    SELECT device_id, ts, zeros_so_far,
           (prev_nz IS NULL OR NOT prev_nz) AS rising,
           lag(ts) OVER (PARTITION BY device_id ORDER BY ts) AS prev_nz_ts
    FROM seq
    WHERE nz
),
grp AS (
    SELECT n.*, sum(CASE WHEN n.rising AND (n.prev_nz_ts IS NULL OR n.ts - n.prev_nz_ts > cfg.win) THEN 1 ELSE 0 END)
                    OVER (PARTITION BY n.device_id ORDER BY n.ts) AS g
    FROM nzr n CROSS JOIN cfg
),
ev AS (
    SELECT device_id, g,
           min(ts) AS started_at,
           max(zeros_so_far) AS zeros_at_end,           -- 事件最后一条非 0 时的 0 行个数
           count(*) FILTER (WHERE rising)::int AS flips
    FROM grp
    GROUP BY device_id, g
)
SELECT ev.device_id::text AS device_id,
       ev.started_at,
       z.ts AS ended_at,
       ev.flips
FROM ev
LEFT JOIN (SELECT device_id, zeros_so_far AS zn, ts FROM seq WHERE NOT nz) z
       ON z.device_id = ev.device_id AND z.zn = ev.zeros_at_end + 1;

-- 只读角色：不存在才建；web 容器用它连库，写入被数据库拒绝（THR-8）。不给序列、不给任何写权限。
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lutetia_ro') THEN
        CREATE ROLE lutetia_ro NOLOGIN;
    END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO lutetia_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO lutetia_ro;   -- 含视图；放在建表建视图之后
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO lutetia_ro;
