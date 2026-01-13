from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def banned_word_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """违禁词菜单键盘

    Args:
        chat_id: 群组ID，用于在私聊中操作群组时指定目标群组
    """
    back_callback = f"adm:back_to_menu:{chat_id}" if chat_id else "adm:menu:main"

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("➕ 添加违禁词", callback_data=f"banned_word:add:{chat_id}" if chat_id else "banned_word:add")],
            [InlineKeyboardButton("📋 查看列表", callback_data=f"banned_word:list:{chat_id}" if chat_id else "banned_word:list")],
            [InlineKeyboardButton("返回", callback_data=back_callback)],
        ]
    )


def banned_word_list_keyboard(words: list, chat_id: int | None = None) -> InlineKeyboardMarkup:
    """违禁词列表键盘

    Args:
        words: 违禁词列表
        chat_id: 群组ID，用于在私聊中操作群组时指定目标群组
    """
    buttons = []
    for word in words:
        status_text = "🔴 暂停" if word.is_active else "🟢 启用"
        # 按钮包含 chat_id，用于私聊模式
        toggle_data = f"banned_word_toggle_{word.id}:{chat_id}" if chat_id else f"banned_word_toggle_{word.id}"
        delete_data = f"banned_word_delete_{word.id}:{chat_id}" if chat_id else f"banned_word_delete_{word.id}"
        buttons.append([
            InlineKeyboardButton(f"{status_text} [{word.id}]", callback_data=toggle_data),
            InlineKeyboardButton("🗑️", callback_data=delete_data),
        ])
    back_callback = f"adm:back_to_menu:{chat_id}" if chat_id else "banned_word:menu"
    buttons.append([InlineKeyboardButton("返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)
