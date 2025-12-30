from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def scheduled_menu_keyboard() -> InlineKeyboardMarkup:
    """定时消息菜单键盘"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 创建定时消息", callback_data="scheduled:create")],
            [InlineKeyboardButton("返回", callback_data="adm:menu:main")],
        ]
    )


def scheduled_list_keyboard(messages: list) -> InlineKeyboardMarkup:
    """定时消息列表键盘"""
    buttons = []
    for msg in messages:
        status_text = "🔴 暂停" if msg.is_active else "🟢 启用"
        buttons.append([
            InlineKeyboardButton(f"{status_text} [{msg.id}]", callback_data=f"scheduled_toggle_{msg.id}"),
            InlineKeyboardButton("🗑️", callback_data=f"scheduled_delete_{msg.id}"),
        ])
    buttons.append([InlineKeyboardButton("返回", callback_data="scheduled:menu")])
    return InlineKeyboardMarkup(buttons)
