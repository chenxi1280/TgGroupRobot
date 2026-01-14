"""开始命令相关的键盘定义"""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def create_start_guide_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """
    创建开始引导按钮键盘

    Args:
        bot_username: 机器人用户名

    Returns:
        引导按钮键盘，点击后跳转到私聊
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 开始", url=f"https://t.me/{bot_username}")],
    ])
