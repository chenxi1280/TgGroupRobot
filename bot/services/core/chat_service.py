from __future__ import annotations

import datetime as dt
import re

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.core import ChatSettings, TgChat
from bot.services.base import ServiceBase


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
    """
    确保群组存在，不存在则创建，存在则更新信息

    同时确保群组设置存在。

    Args:
        session: 数据库会话
        chat_id: Telegram 群组 ID
        chat_type: 群组类型
        title: 群组标题

    Returns:
        TgChat: 群组对象
    """
    chat = await ServiceBase._get_by_id(session, TgChat, chat_id)
    if chat is None:
        chat = TgChat(id=chat_id, type=chat_type, title=title)
        session.add(chat)
        await session.flush()
    else:
        await ServiceBase._update_entity(
            session,
            chat,
            {
                "title": title,
                "type": chat_type,
                "updated_at": dt.datetime.now(dt.UTC),
            },
        )

    # 确保设置存在
    settings = await ServiceBase._get_by_filters(
        session,
        ChatSettings,
        {"chat_id": chat_id},
    )
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await session.flush()

    return chat


async def get_chat_settings(session: AsyncSession, chat_id: int) -> ChatSettings:
    """
    获取群组设置，如果不存在则创建默认设置

    Args:
        session: 数据库会话
        chat_id: Telegram 群组 ID

    Returns:
        ChatSettings: 群组设置对象
    """
    settings = await ServiceBase._get_by_filters(
        session,
        ChatSettings,
        {"chat_id": chat_id},
    )
    if settings is None:
        settings = ChatSettings(chat_id=chat_id)
        session.add(settings)
        await session.flush()
    return settings





