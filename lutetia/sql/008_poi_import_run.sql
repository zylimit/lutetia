-- 每次成功的 `lutetia import poi`（非 dry-run）记一行（Task 10.2 审查 M-1 / #109）：原样重导入未变的台账时，poi 行的
-- imported_at 不动（只有内容变了才刷新），「Excel snapshot, as of …」会停在上一次有变化的导入；有了这张表，/api/v1/pois 与
-- summary 的 POI as_of 取最新一次导入的时间，重导入后 as_of 前进。只存计数与文件摘要，不存任何单元格内容。
-- IF NOT EXISTS：每次部署重跑不报错、不动已有行。
CREATE TABLE IF NOT EXISTS poi_import_run (
    id          bigserial   PRIMARY KEY,
    imported_at timestamptz NOT NULL DEFAULT now(),
    file_sha256 text        NOT NULL,
    total       int         NOT NULL,  -- 台账里读到的工单数
    changed     int         NOT NULL,  -- new + updated
    gone        int         NOT NULL,  -- 本次标成「台账已无」的工单数
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS poi_import_run_imported_at_idx ON poi_import_run (imported_at);

-- 只读角色：显式授权，不依赖 005 默认权限的执行顺序
GRANT SELECT ON poi_import_run TO lutetia_ro;
