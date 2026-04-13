"""违禁词键盘

提供违禁词管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.ui.base.helpers import create_back_button
from backend.shared.ui.formatters import StatusIcons


def banned_word_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """违禁词菜单键盘

    Args:
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    add_callback = (
        f"banned_word:add:{chat_id}"
        if chat_id
        else "banned_word:add"
    )
    list_callback = (
        f"banned_word:list:{chat_id}"
        if chat_id
        else "banned_word:list"
    )
    back_button = create_back_button(chat_id, "back_to_menu")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 添加违禁词", callback_data=add_callback)],
        [InlineKeyboardButton("📋 查看列表", callback_data=list_callback)],
        [back_button],
    ])


def banned_word_list_keyboard(
    words: list,
    chat_id: int | None = None,
) -> InlineKeyboardMarkup:
    """违禁词列表键盘

    Args:
        words: 违禁词列表
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    buttons = []

    for word in words:
        status_icon = StatusIcons.active(word.is_active)
        label = f"{status_icon} [{word.id}]"

        # 私聊模式下需要包含 chat_id
        chat_suffix = f":{chat_id}" if chat_id else ""
        toggle_callback = f"banned_word_toggle_{word.id}{chat_suffix}"
        delete_callback = f"banned_word_delete_{word.id}{chat_suffix}"

        buttons.append([
            InlineKeyboardButton(label, callback_data=toggle_callback),
            InlineKeyboardButton("🗑️", callback_data=delete_callback),
        ])

    # 返回按钮
    back_callback = (
        f"adm:back_to_menu:{chat_id}"
        if chat_id
        else "banned_word:menu"
    )
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])

    return InlineKeyboardMarkup(buttons)
