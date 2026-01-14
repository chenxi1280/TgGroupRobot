"""定时消息键盘

提供定时消息管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.base.helpers import create_back_button
from bot.keyboards.formatters import StatusIcons


def scheduled_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """定时消息菜单键盘

    Args:
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    create_callback = (
        f"scheduled:create:{chat_id}"
        if chat_id
        else "scheduled:create"
    )
    list_callback = (
        f"scheduled:list:{chat_id}"
        if chat_id
        else "scheduled:list"
    )
    back_button = create_back_button(chat_id, "back_to_menu")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 创建定时消息", callback_data=create_callback)],
        [InlineKeyboardButton("📋 查看列表", callback_data=list_callback)],
        [back_button],
    ])


def scheduled_list_keyboard(
    messages: list,
    chat_id: int | None = None,
) -> InlineKeyboardMarkup:
    """定时消息列表键盘

    Args:
        messages: 定时消息列表
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    buttons = []

    for msg in messages:
        status_icon = StatusIcons.active(msg.is_active)
        label = f"{status_icon} [{msg.id}]"

        toggle_callback = f"scheduled_toggle_{msg.id}"
        delete_callback = f"scheduled_delete_{msg.id}"

        buttons.append([
            InlineKeyboardButton(label, callback_data=toggle_callback),
            InlineKeyboardButton("🗑️", callback_data=delete_callback),
        ])

    # 返回按钮
    back_callback = (
        f"adm:back_to_menu:{chat_id}"
        if chat_id
        else "scheduled:menu"
    )
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])

    return InlineKeyboardMarkup(buttons)
