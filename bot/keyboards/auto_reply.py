from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def auto_reply_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """自动回复菜单键盘

    Args:
        chat_id: 群组ID，用于在私聊中操作群组时指定目标群组
    """
    back_callback = f"adm:back_to_menu:{chat_id}" if chat_id else "adm:menu:main"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 创建自动回复规则", callback_data="auto_reply:create")],
            [InlineKeyboardButton("返回", callback_data=back_callback)],
        ]
    )


def auto_reply_list_keyboard(rules: list, chat_id: int | None = None) -> InlineKeyboardMarkup:
    """自动回复规则列表键盘

    Args:
        rules: 自动回复规则列表
        chat_id: 群组ID，用于在私聊中操作群组时指定目标群组
    """
    buttons = []
    for rule in rules:
        status_text = "🔴 暂停" if rule.is_active else "🟢 启用"
        buttons.append([
            InlineKeyboardButton(f"{status_text} [{rule.id}]", callback_data=f"auto_reply_toggle_{rule.id}"),
            InlineKeyboardButton("🗑️", callback_data=f"auto_reply_delete_{rule.id}"),
        ])
    back_callback = f"adm:back_to_menu:{chat_id}" if chat_id else "auto_reply:menu"
    buttons.append([InlineKeyboardButton("返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)
