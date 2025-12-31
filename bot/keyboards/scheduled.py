from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def scheduled_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """定时消息菜单键盘

    Args:
        chat_id: 群组ID，用于在私聊中操作群组时指定目标群组
    """
    back_callback = f"adm:back_to_menu:{chat_id}" if chat_id else "adm:menu:main"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 创建定时消息", callback_data="scheduled:create")],
            [InlineKeyboardButton("返回", callback_data=back_callback)],
        ]
    )


def scheduled_list_keyboard(messages: list, chat_id: int | None = None) -> InlineKeyboardMarkup:
    """定时消息列表键盘

    Args:
        messages: 定时消息列表
        chat_id: 群组ID，用于在私聊中操作群组时指定目标群组
    """
    buttons = []
    for msg in messages:
        status_text = "🔴 暂停" if msg.is_active else "🟢 启用"
        buttons.append([
            InlineKeyboardButton(f"{status_text} [{msg.id}]", callback_data=f"scheduled_toggle_{msg.id}"),
            InlineKeyboardButton("🗑️", callback_data=f"scheduled_delete_{msg.id}"),
        ])
    back_callback = f"adm:back_to_menu:{chat_id}" if chat_id else "scheduled:menu"
    buttons.append([InlineKeyboardButton("返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)
