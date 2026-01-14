from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ChatSettings, TgChat


# ==================== 辅助函数 ====================


def get_settings_toggle_rows(settings: ChatSettings) -> list[tuple[str, str, bool]]:
    """
    生成设置开关行数据

    Args:
        settings: 群组设置对象

    Returns:
        开关行列表 [(标签, 字段名, 启用状态), ...]
    """
    return [
        ("签到", "sign_enabled", settings.sign_enabled),
        ("进群欢迎", "welcome_enabled", settings.welcome_enabled),
        ("新人验证", "verification_enabled", settings.verification_enabled),
        ("内容审核", "moderation_enabled", settings.moderation_enabled),
        ("屏蔽链接", "moderation_block_links", settings.moderation_block_links),
        ("反刷屏", "anti_flood_enabled", settings.anti_flood_enabled),
        ("广告", "ads_enabled", settings.ads_enabled),
        ("商业化", "monetization_enabled", settings.monetization_enabled),
    ]


def build_points_alias_patterns(settings: ChatSettings) -> dict[str, re.Pattern]:
    """
    构建积分别名正则表达式

    Args:
        settings: 群组设置对象

    Returns:
        别名正则字典 {"points": pattern, "rank": pattern}
    """
    return {
        "points": re.compile(rf"^{re.escape(settings.points_alias)}$"),
        "rank": re.compile(rf"^{re.escape(settings.points_rank_alias)}$"),
    }


async def ensure_chat(session: AsyncSession, chat_id: int, chat_type: str, title: str | None) -> TgChat:
    res = await session.execute(select(TgChat).where(TgChat.id == chat_id))
    chat = res.scalar_one_or_none()
    if chat is None:
        chat = TgChat(id=chat_id, type=chat_type, title=title)
        session.add(chat)
        await session.flush()
    else:
        chat.title = title
        chat.type = chat_type
        chat.updated_at = dt.datetime.now(dt.UTC)

    res2 = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
    settings = res2.scalar_one_or_none()
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await session.flush()
    return chat


async def get_chat_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    """获取群组设置，如果不存在则创建默认设置"""
    res = await session.execute(select(ChatSettings).where(ChatSettings.chat_id == chat_id))
    settings = res.scalar_one_or_none()
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await session.flush()
    return settings





