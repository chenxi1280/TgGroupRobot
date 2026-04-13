"""为 chat_settings 增加防刷屏扩展字段和反垃圾配置字段"""
from __future__ import annotations

import asyncio
import sys

# Windows 系统需要使用 WindowsSelectorEventLoopPolicy
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


COLUMNS_SQL = [
    "ALTER TABLE bot.chat_settings ALTER COLUMN anti_flood_mute_duration SET DEFAULT 3600;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_cleanup_messages BOOLEAN NOT NULL DEFAULT FALSE;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_delete_notify BOOLEAN NOT NULL DEFAULT FALSE;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_flood_delete_notify_seconds INTEGER NOT NULL DEFAULT 600;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_enabled BOOLEAN NOT NULL DEFAULT FALSE;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_action VARCHAR(32) NOT NULL DEFAULT 'mute';",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_mute_duration INTEGER NOT NULL DEFAULT 3600;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_exempt_admin BOOLEAN NOT NULL DEFAULT TRUE;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_delete_notify BOOLEAN NOT NULL DEFAULT FALSE;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_delete_notify_seconds INTEGER NOT NULL DEFAULT 600;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_repeat_messages INTEGER NOT NULL DEFAULT 3;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_repeat_seconds INTEGER NOT NULL DEFAULT 15;",
    "ALTER TABLE bot.chat_settings ADD COLUMN IF NOT EXISTS anti_spam_rules JSONB NOT NULL DEFAULT '{}'::jsonb;",
]


async def migrate() -> None:
    from sqlalchemy import text

    from backend.platform.config.core.settings import get_settings
    from backend.platform.db.runtime.session import create_database

    settings = get_settings()
    db = create_database(settings.database_url)

    async with db.session_factory() as session:
        for sql in COLUMNS_SQL:
            await session.execute(text(sql))
        await session.commit()

    print("[OK] chat_settings columns migration completed")


if __name__ == "__main__":
    asyncio.run(migrate())
