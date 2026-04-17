from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.ui.base.helpers import create_back_button


def sm_list_keyboard(tasks: list, chat_id: int, page: int = 0, page_size: int = 10) -> InlineKeyboardMarkup:
    buttons = []
    start_idx = page * page_size
    end_idx = start_idx + page_size

    for task in tasks[start_idx:end_idx]:
        buttons.append([
            InlineKeyboardButton(f"🔢 编号:{task.short_id}", callback_data=f"sm:open:{chat_id}:{task.short_id}"),
            InlineKeyboardButton(
                "❌ 关闭" if task.enabled else "✅ 启用",
                callback_data=f"sm:set:{chat_id}:{task.short_id}:enabled:{0 if task.enabled else 1}",
            ),
            InlineKeyboardButton("✏️ 修改", callback_data=f"sm:open:{chat_id}:{task.short_id}"),
            InlineKeyboardButton("🗑 删除", callback_data=f"sm:del_confirm:{chat_id}:{task.short_id}"),
        ])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"sm:list:{chat_id}:{page-1}"))
    if end_idx < len(tasks):
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"sm:list:{chat_id}:{page+1}"))
    if nav_buttons:
        buttons.append(nav_buttons)

    buttons.extend([
        [InlineKeyboardButton("➕ 添加一条", callback_data=f"sm:add:{chat_id}")],
        [create_back_button(chat_id, "main")],
    ])
    return InlineKeyboardMarkup(buttons)
