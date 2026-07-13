# Alembic 与严格 Schema Gate 实施计划

1. 先补迁移编排测试，覆盖未纳管库、已纳管库、执行顺序和错误上抛。
2. 建立 async Alembic 环境、legacy baseline 与四个可靠性领域 revision。
3. 将旧启动补丁改名为一次性 legacy bootstrap，并由统一迁移编排器调用。
4. Bot 与 init_db 无条件执行迁移，再执行只读 Schema Gate；删除跳过开关与 PTB 告警过滤。
5. 拆分 Schema Gate 的结构采集与规范化比较，汇总类型、nullable、默认值、外键和索引差异。
6. 执行迁移单测、Schema Gate 单测和全量 `pytest -W error`，再提交本批变更。
