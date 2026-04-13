"""添加 short_id 列到 scheduled_message_tasks 表"""
from __future__ import annotations

import asyncio
import secrets
import sys

# Windows 系统需要使用 WindowsSelectorEventLoopPolicy
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def add_short_id_column():
    """添加 short_id 列并为现有数据生成短 ID"""
    from backend.platform.config.core.settings import get_settings
    from backend.platform.db.runtime.session import create_database
    from sqlalchemy import text, select
    from backend.platform.db.schema.models.scheduled_message import ScheduledMessageTask

    settings = get_settings()
    db = create_database(settings.database_url)

    async with db.session_factory() as session:
        # 检查列是否已存在
        check_column_sql = """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='bot' AND table_name='scheduled_message_tasks' AND column_name='short_id';
        """
        result = await session.execute(text(check_column_sql))
        column_exists = result.scalar_one_or_none()

        if not column_exists:
            # 添加 short_id 列（可为空）
            add_column_sql = """
            ALTER TABLE bot.scheduled_message_tasks
            ADD COLUMN short_id VARCHAR(8);
            """
            await session.execute(text(add_column_sql))
            print("[OK] Column short_id added")
        else:
            print("[INFO] Column short_id already exists")

        # 为现有数据生成短 ID
        result = await session.execute(
            select(ScheduledMessageTask).where(ScheduledMessageTask.short_id == None)
        )
        tasks = result.scalars().all()

        if tasks:
            print(f"[INFO] Generating short_id for {len(tasks)} existing tasks...")
            for task in tasks:
                # 生成唯一的短 ID
                while True:
                    short_id = secrets.token_hex(4)  # 8 个字符
                    # 检查是否已存在
                    existing = await session.execute(
                        select(ScheduledMessageTask).where(ScheduledMessageTask.short_id == short_id)
                    )
                    if not existing.scalar_one_or_none():
                        task.short_id = short_id
                        break

            await session.commit()
            print(f"[OK] Generated short_id for {len(tasks)} tasks")
        else:
            print("[INFO] No tasks need short_id")

        # 添加 NOT NULL 和 UNIQUE 约束
        if not column_exists:
            try:
                alter_column_sql = """
                ALTER TABLE bot.scheduled_message_tasks
                ALTER COLUMN short_id SET NOT NULL,
                ADD CONSTRAINT scheduled_message_tasks_short_id_key UNIQUE (short_id);
                """
                await session.execute(text(alter_column_sql))
                print("[OK] Constraints added")
            except Exception as e:
                print(f"[WARNING] Could not add constraints: {e}")

        # 创建索引（如果不存在）
        try:
            create_index_sql = """
            CREATE INDEX IF NOT EXISTS ix_smt_short_id
            ON bot.scheduled_message_tasks(short_id);
            """
            await session.execute(text(create_index_sql))
            print("[OK] Index created")
        except Exception as e:
            print(f"[WARNING] Could not create index: {e}")

    print("\nMigration completed!")


if __name__ == "__main__":
    asyncio.run(add_short_id_column())
