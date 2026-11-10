-- SLA 时长前缀里的层级（Task 10.2 审查 ❓2）：「接入层：1吨/天」的「接入层」解析成 access，前端显示「Access layer: 1 t/day」。
-- 接入层 → access、汇聚层 → aggregation、主干层 / 骨干层 → backbone，其它前缀 → other（前端注「scope in source table」），
-- 无前缀或时长没解析出来为 NULL。只增：ADD COLUMN IF NOT EXISTS，每次部署重跑不报错；表级只读授权（006）已覆盖新列。
-- 本迁移之前导入的行为 NULL，重跑一次 `lutetia import sla` 即补上。
ALTER TABLE sla_template_step ADD COLUMN IF NOT EXISTS sla_scope text
    CHECK (sla_scope IN ('access', 'aggregation', 'backbone', 'other'));
