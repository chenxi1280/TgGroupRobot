from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from backend.platform.db.schema.models.core import ChatSettings, TgChat
from backend.shared.services.base import ServiceBase
from backend.shared.services.module_settings_service import ModuleSettingsService


# ==================== 辅助函数 ====================


# 允许通过 toggle 回调切换的字段白名单（仅布尔类型字段）
SETTINGS_TOGGLE_FIELDS: set[str] = {
    "sign_enabled",
    "welcome_enabled",
    "verification_enabled",
    "moderation_enabled",
    "moderation_block_links",
    "anti_flood_enabled",
    "anti_spam_enabled",
    "ads_enabled",
    "monetization_enabled",
}


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
        ("反垃圾", "anti_spam_enabled", settings.anti_spam_enabled),
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


async def ensure_chat(session: AsyncSession, chat_id: int, chat_type: str, *, title: str | None) -> TgChat:
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
    await ModuleSettingsService.ensure(
        session,
        chat_id=chat_id,
        chat_type=chat_type,
        title=title,
    )
    chat = await ServiceBase._get_by_id(session, TgChat, chat_id)
    if chat is None:
        chat = TgChat(id=chat_id, type=chat_type, title=title)
        session.add(chat)
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

    注意：
        当 chat_id=0 时，返回一个临时的默认设置对象，不保存到数据库
    """
    # chat_id=0 表示不需要数据库设置（如某些通用操作）
    # 返回一个临时的默认设置对象
    if chat_id == 0:
        return ChatSettings(chat_id=0)

    return await ModuleSettingsService.ensure(
        session,
        chat_id=chat_id,
        chat_type="supergroup" if chat_id < 0 else "private",
        title=None,
    )

