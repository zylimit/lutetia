-- SLA 时长解析结果（Decisions 2026-11-10）：sla_text 原文照存，另存 数值 + 单位，前端按英 / 法显示，不显示中文原文。
-- 范围写法（「1-2天」）sla_value 存上限、sla_value_min 存下限；单个值 sla_value_min 为 NULL；解析不了三列都为 NULL。
-- ADD COLUMN IF NOT EXISTS：每次部署重跑不报错；列已存在时整条列定义（含 CHECK）跳过，不会重复加约束。
-- 006 已对整表 GRANT SELECT 给 lutetia_ro，表级授权覆盖新列，这里不用再授。
-- 本迁移之前导入的行三列为 NULL（显示「—」），重跑一次 `lutetia import sla` 即补上。
ALTER TABLE sla_template_step ADD COLUMN IF NOT EXISTS sla_value numeric;
ALTER TABLE sla_template_step ADD COLUMN IF NOT EXISTS sla_value_min numeric;
ALTER TABLE sla_template_step ADD COLUMN IF NOT EXISTS sla_unit text
    CHECK (sla_unit IN ('minute', 'hour', 'day', 'workday', 'week', 'month', 'tonne_per_day'));
