"""数据库运行时层（session / schema lifecycle）。

启动顺序（见 ``app/bootstrap.py::_validate_schema_or_exit`` 与
``db/init_db.py::init_db``）：

1. ``session.create_database(url)`` — 构建 ``AsyncEngine`` + ``session_factory``
2. ``database_migrations.migrate_database(engine)``
   - 未纳管数据库显式执行一次 legacy bootstrap 并 stamp baseline
   - 已纳管数据库只执行 ``alembic upgrade head``
   - 任一步失败都会拒绝启动
3. ``schema_gate.validate_database_schema(engine)``
   - 严格只读校验表、字段属性、外键、索引和唯一约束
   - 汇总全部差异后抛 ``SchemaValidationError`` 拒绝启动
4. 调度器启动（``Scheduler.start()``），任务执行时库结构已就绪

新增表/字段/索引时：
- 在 ``backend/platform/db/schema/models/`` 下声明 ORM 模型
- 在 ``alembic/versions`` 新增带 downgrade 的 revision
- 如有必须存在的索引，在 ``schema_gate.REQUIRED_INDEXES`` 追加声明
"""

__all__ = []
