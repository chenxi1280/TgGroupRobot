"""通用验证器函数"""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram.ext import Application


async def validate_user_permission(
    app: "Application",
    chat_id: int,
    user_id: int,
) -> bool:
    """
    验证用户是否有权限操作

    Args:
        app: Telegram Bot Application 实例
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        用户是否有权限
    """
    from bot.services.core.permission_service import is_user_admin
    return await is_user_admin(app, chat_id, user_id)


async def validate_bot_permission(
    app: "Application",
    chat_id: int,
    required_permission: str,
) -> bool:
    """
    验证机器人是否有权限

    Args:
        app: Telegram Bot Application 实例
        chat_id: 群组ID
        required_permission: 需要的权限类型（如 "can_delete_messages"）

    Returns:
        机器人是否有权限
    """
    try:
        bot = app.bot
        chat = await bot.get_chat(chat_id)

        # 获取机器人成员信息
        bot_member = await chat.get_member(bot.id)

        # 检查权限
        if required_permission == "can_delete_messages":
            return bot_member.can_delete_messages
        elif required_permission == "can_restrict_members":
            return bot_member.can_restrict_members
        elif required_permission == "can_promote_members":
            return bot_member.can_promote_members
        elif required_permission == "is_administrator":
            return bot_member.status in ["administrator", "creator"]
        else:
            return True
    except Exception:
        return False


def validate_positive_number(value: int, field_name: str = "数值") -> tuple[bool, str | None]:
    """
    验证数值是否为正数

    Args:
        value: 要验证的数值
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if value is None:
        return True, None

    if not isinstance(value, (int, float)):
        return False, f"{field_name}必须是数字"

    if value < 0:
        return False, f"{field_name}不能为负数"

    return True, None


def validate_future_time(time: dt.datetime, field_name: str = "时间") -> tuple[bool, str | None]:
    """
    验证时间是否为未来时间

    Args:
        time: 要验证的时间
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if time is None:
        return True, None

    now = dt.datetime.now(dt.timezone.utc)

    if time.tzinfo is None:
        return False, f"{field_name}必须包含时区信息"

    if time <= now:
        return False, f"{field_name}必须是未来时间"

    return True, None


def validate_string_length(
    text: str,
    min_length: int = 0,
    max_length: int = 1000,
    field_name: str = "文本",
) -> tuple[bool, str | None]:
    """
    验证字符串长度

    Args:
        text: 要验证的文本
        min_length: 最小长度
        max_length: 最大长度
        field_name: 字段名称（用于错误消息）

    Returns:
        (是否有效, 错误信息)
    """
    if text is None:
        return True, None

    length = len(text)

    if length < min_length:
        return False, f"{field_name}长度不能少于{min_length}个字符"

    if length > max_length:
        return False, f"{field_name}长度不能超过{max_length}个字符"

    return True, None


async def validate_user_in_group(
    app: "Application",
    chat_id: int,
    user_id: int,
) -> bool:
    """
    验证用户是否在群组中

    Args:
        app: Telegram Bot Application 实例
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        用户是否在群组中
    """
    try:
        bot = app.bot
        chat = await bot.get_chat(chat_id)
        member = await chat.get_member(user_id)
        return member is not None
    except Exception:
        return False


async def validate_user_is_admin(
    app: "Application",
    chat_id: int,
    user_id: int,
) -> tuple[bool, str | None]:
    """
    验证用户是否是管理员

    Args:
        app: Telegram Bot Application 实例
        chat_id: 群组ID
        user_id: 用户ID

    Returns:
        (是否是管理员, 错误信息)
    """
    is_admin = await validate_user_permission(app, chat_id, user_id)
    if is_admin:
        return True, None
    return False, "需要管理员权限"
