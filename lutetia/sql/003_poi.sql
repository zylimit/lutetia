-- POI 台账（运维手工 Excel 导入）：工单一张表、电缆段一张表。全部 IF NOT EXISTS，每次部署重跑不报错、不动已导入的数据。
-- 不碰现有五张表与两个视图。

CREATE TABLE IF NOT EXISTS poi (
    poi_no            text PRIMARY KEY,
    uci               text,
    subcon            text,
    site_ville        text,
    commune_code      text,
    category          text,
    status_raw        text,
    occ_week_from     int,
    occ_week_to       int,
    occ_date_from     date,
    occ_date_to       date,
    received_date     date,
    planned_op_date   date,
    -- 台账里已无该工单时置 false，不删行：消失的单标「台账已无」而不是丢掉
    in_ledger         boolean NOT NULL DEFAULT true,
    -- content_sha：业务字段 + 有序段的指纹，变了才算 updated；raw_sha：未映射原文列的指纹，只变它只刷新 raw
    content_sha       text NOT NULL,
    raw_sha           text NOT NULL,
    raw               jsonb,
    first_imported_at timestamptz NOT NULL DEFAULT now(),
    imported_at       timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS poi_cable_segment (
    poi_no         text NOT NULL REFERENCES poi(poi_no) ON DELETE CASCADE,
    seq            int NOT NULL,
    cable_category text,
    cable_type     text,
    infra          text,
    length_km      numeric,
    weight_t       numeric,
    ref_min_t      numeric,
    ref_avg_t      numeric,
    ref_max_t      numeric,
    raw            jsonb,
    PRIMARY KEY (poi_no, seq)
);

CREATE INDEX IF NOT EXISTS poi_uci_idx ON poi (uci);
CREATE INDEX IF NOT EXISTS poi_subcon_idx ON poi (subcon);
CREATE INDEX IF NOT EXISTS poi_occ_week_from_idx ON poi (occ_week_from);
