from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def auto_reply_menu_keyboard() -> InlineKeyboardMarkup:
    """自动回复菜单键盘"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 创建自动回复规则", callback_data="auto_reply:create")],
            [InlineKeyboardButton("返回", callback_data="adm:menu:main")],
        ]
    )


def auto_reply_list_keyboard(rules: list) -> InlineKeyboardMarkup:
    """自动回复规则列表键盘"""
    buttons = []
    for rule in rules:
        status_text = "🔴 暂停" if rule.is_active else "🟢 启用"
        buttons.append([
            InlineKeyboardButton(f"{status_text} [{rule.id}]", callback_data=f"auto_reply_toggle_{rule.id}"),
            InlineKeyboardButton("🗑️", callback_data=f"auto_reply_delete_{rule.id}"),
        ])
    buttons.append([InlineKeyboardButton("返回", callback_data="auto_reply:menu")])
    return InlineKeyboardMarkup(buttons)
