"""创建定时消息任务表的迁移脚本"""
from __future__ import annotations

import asyncio
import sys

# Windows 系统需要使用 WindowsSelectorEventLoopPolicy
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def create_tables():
    """创建定时消息任务表"""
    from backend.platform.config.core.settings import get_settings
    from backend.platform.db.runtime.session import create_database
    from sqlalchemy import text

    settings = get_settings()
    db = create_database(settings.database_url)

    # 创建表的 SQL
    create_tasks_table = """
    CREATE TABLE IF NOT EXISTS bot.scheduled_message_tasks (
        task_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        chat_id BIGINT NOT NULL,
        created_by_user_id BIGINT,
        title VARCHAR(128) NOT NULL,
        enabled BOOLEAN NOT NULL DEFAULT TRUE,

        -- 重复配置
        repeat_interval_min INTEGER NOT NULL DEFAULT 60,
        day_start_hour INTEGER NOT NULL DEFAULT 0,
        day_end_hour INTEGER NOT NULL DEFAULT 23,

        -- 时间范围
        start_at BIGINT,
        end_at BIGINT,

        -- 内容
        text TEXT,
        parse_mode VARCHAR(16) NOT NULL DEFAULT 'HTML',
        media_type VARCHAR(16) NOT NULL DEFAULT 'none',
        media_file_id VARCHAR(256),
        buttons JSONB NOT NULL DEFAULT '[]',

        -- 发送选项
        delete_previous BOOLEAN NOT NULL DEFAULT TRUE,
        pin_message BOOLEAN NOT NULL DEFAULT FALSE,

        -- 执行状态
        last_sent_message_id INTEGER,
        next_run_at BIGINT,

        -- 时间戳
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

        CONSTRAINT fk_smt_chat_id FOREIGN KEY (chat_id)
            REFERENCES bot.tg_chats(id) ON DELETE CASCADE,
        CONSTRAINT fk_smt_created_by FOREIGN KEY (created_by_user_id)
            REFERENCES bot.tg_users(id) ON DELETE SET NULL
    );

    -- 索引
    CREATE INDEX IF NOT EXISTS ix_smt_chat_id ON bot.scheduled_message_tasks(chat_id);
    CREATE INDEX IF NOT EXISTS ix_smt_enabled ON bot.scheduled_message_tasks(enabled);
    CREATE INDEX IF NOT EXISTS ix_smt_next_run_at ON bot.scheduled_message_tasks(next_run_at)
        WHERE enabled = TRUE;
    """

    create_logs_table = """
    CREATE TABLE IF NOT EXISTS bot.scheduled_message_logs (
        id BIGSERIAL PRIMARY KEY,
        task_id UUID NOT NULL,
        chat_id BIGINT NOT NULL,
        message_id INTEGER,
        sent_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        success BOOLEAN NOT NULL,
        error_message TEXT,

        CONSTRAINT fk_sml_task_id FOREIGN KEY (task_id)
            REFERENCES bot.scheduled_message_tasks(task_id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS ix_sml_task_id ON bot.scheduled_message_logs(task_id);
    CREATE INDEX IF NOT EXISTS ix_sml_sent_at ON bot.scheduled_message_logs(sent_at);
    """

    async with db.session_factory() as session:
        # 创建任务表
        await session.execute(text(create_tasks_table))
        print("[OK] Scheduled message tasks table created successfully!")

        # 创建日志表
        await session.execute(text(create_logs_table))
        print("[OK] Scheduled message logs table created successfully!")

        await session.commit()

    print("\nAll tables created! You can now start the bot.")


if __name__ == "__main__":
    asyncio.run(create_tables())
