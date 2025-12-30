from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def banned_word_menu_keyboard() -> InlineKeyboardMarkup:
    """违禁词菜单键盘"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 添加违禁词", callback_data="banned_word:add")],
            [InlineKeyboardButton("返回", callback_data="adm:menu:main")],
        ]
    )


def banned_word_list_keyboard(words: list) -> InlineKeyboardMarkup:
    """违禁词列表键盘"""
    buttons = []
    for word in words:
        status_text = "🔴 暂停" if word.is_active else "🟢 启用"
        buttons.append([
            InlineKeyboardButton(f"{status_text} [{word.id}]", callback_data=f"banned_word_toggle_{word.id}"),
            InlineKeyboardButton("🗑️", callback_data=f"banned_word_delete_{word.id}"),
        ])
    buttons.append([InlineKeyboardButton("返回", callback_data="banned_word:menu")])
    return InlineKeyboardMarkup(buttons)
