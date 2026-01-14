"""开始引导键盘

提供开始命令相关的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardMarkup

from bot.keyboards.base.helpers import create_link_button


def create_start_guide_keyboard(bot_username: str) -> InlineKeyboardMarkup:
    """创建开始引导按钮键盘

    Args:
        bot_username: 机器人用户名

    Returns:
        引导按钮键盘，点击后跳转到私聊
    """
    button = create_link_button("🚀 开始", f"https://t.me/{bot_username}")
    return InlineKeyboardMarkup([[button]])
