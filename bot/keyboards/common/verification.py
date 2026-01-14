"""验证键盘

提供人机验证相关的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardMarkup

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
