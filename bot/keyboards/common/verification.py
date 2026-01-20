"""验证键盘

提供人机验证相关的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.base.builders import KeyboardBuilder


def verification_keyboard(token: str) -> InlineKeyboardMarkup:
    """创建验证键盘

    Args:
        token: 验证令牌

    Returns:
        验证键盘，包含"我不是机器人"按钮
    """
    builder = KeyboardBuilder("vfy")
    builder.add_button("我不是机器人", "verify", token)
    return builder.build()


def admin_verify_keyboard(user_id: int, token: str) -> InlineKeyboardMarkup:
    """创建管理员确认验证键盘

    Args:
        user_id: 待验证用户 ID
        token: 验证令牌

    Returns:
        管理员确认键盘，包含通过和拒绝按钮
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 通过", callback_data=f"adm_vfy:{user_id}:{token}:approve"),
            InlineKeyboardButton("❌ 拒绝", callback_data=f"adm_vfy:{user_id}:{token}:reject"),
        ]
    ])
