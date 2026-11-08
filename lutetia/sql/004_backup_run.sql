-- 备份记录：deploy/backup.sh 每次运行（成功或失败）插一行。全部 IF NOT EXISTS，每次部署重跑不报错、不动已有记录。
-- 不碰现有表与视图。row_counts 是 dump 前记下的各表行数，恢复演练拿它核对。

CREATE TABLE IF NOT EXISTS backup_run (
    id          bigserial PRIMARY KEY,
    started_at  timestamptz NOT NULL,
    finished_at timestamptz,
    ok          boolean NOT NULL,
    -- 周日（Europe/Paris）为 weekly，其余 daily；周日那次同时上传到 daily/ 与 weekly/，只记一行
    kind        text NOT NULL CHECK (kind IN ('daily', 'weekly')),
    -- 上传成功才有；--local-only 或上传失败时为 NULL
    object_key  text,
    bytes       bigint,
    sha256      text,
    row_counts  jsonb,
    -- dump 之后再数一次；表只增不删，恢复值应满足 row_counts <= 恢复值 <= row_counts_after
    row_counts_after jsonb,
    -- 失败原因，只写阶段与退出码，不写凭据
    error       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS backup_run_finished_at_idx ON backup_run (finished_at DESC);
