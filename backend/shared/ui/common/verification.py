"""验证键盘

提供人机验证相关的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def verification_keyboard(token: str) -> InlineKeyboardMarkup:
    """创建验证键盘

    Args:
        token: 验证令牌

    Returns:
        验证键盘，包含同意和不同意按钮
    """
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 同意", callback_data=f"vfy:{token}:agree"),
            InlineKeyboardButton("❌ 不同意", callback_data=f"vfy:{token}:decline"),
        ]
    ])


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


def verification_timeout_help_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """验证超时后的协助键盘

    Args:
        user_id: 被禁言用户 ID
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🙋 我是本人，申请解封", callback_data=f"vfy_help:appeal:{user_id}")],
        [InlineKeyboardButton("🛡️ 管理员一键解封", callback_data=f"vfy_help:unmute:{user_id}")],
    ])
