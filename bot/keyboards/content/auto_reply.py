"""自动回复键盘

提供自动回复规则管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.base.helpers import create_back_button
from bot.keyboards.formatters import StatusIcons


def auto_reply_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """自动回复菜单键盘

    Args:
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    create_callback = (
        f"auto_reply:create:{chat_id}"
        if chat_id
        else "auto_reply:create"
    )
    list_callback = (
        f"auto_reply:list:{chat_id}"
        if chat_id
        else "auto_reply:list"
    )
    back_button = create_back_button(chat_id, "back_to_menu")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 创建自动回复规则", callback_data=create_callback)],
        [InlineKeyboardButton("📋 管理自动回复规则", callback_data=list_callback)],
        [back_button],
    ])


def auto_reply_list_keyboard(
    rules: list,
    chat_id: int | None = None,
) -> InlineKeyboardMarkup:
    """自动回复规则列表键盘

    Args:
        rules: 自动回复规则列表
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    buttons = []

    for rule in rules:
        status_icon = StatusIcons.active(rule.is_active)
        label = f"{status_icon} [{rule.id}]"

        toggle_callback = f"auto_reply_toggle_{rule.id}"
        delete_callback = f"auto_reply_delete_{rule.id}"

        buttons.append([
            InlineKeyboardButton(label, callback_data=toggle_callback),
            InlineKeyboardButton("🗑️", callback_data=delete_callback),
        ])

    # 返回按钮
    back_callback = (
        f"adm:back_to_menu:{chat_id}"
        if chat_id
        else "auto_reply:menu"
    )
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])

    return InlineKeyboardMarkup(buttons)
