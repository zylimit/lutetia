-- SLA 流程模板（DEPOSE-* 三份 Excel 导入）：每个模板一串有序节点。只作流程参考，不对任何一单算超时（OUT-9）。
-- IF NOT EXISTS，每次部署重跑不报错、不动已导入的数据。sla_text 是 SLA 时长原文，表里没写的节点为 NULL。
CREATE TABLE IF NOT EXISTS sla_template_step (
    template    text NOT NULL,
    seq         int  NOT NULL,
    step        text NOT NULL,
    owner       text NOT NULL CHECK (owner IN ('customer', 'huawei', 'partner')),
    sla_text    text,
    imported_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (template, seq)
);

-- 只读角色：005 的 ALTER DEFAULT PRIVILEGES 只管之后由同一属主建的表；这里显式再授一次，不依赖执行顺序
GRANT SELECT ON sla_template_step TO lutetia_ro;
