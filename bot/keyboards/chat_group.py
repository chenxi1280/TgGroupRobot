from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def chat_group_list_keyboard(chats: list[tuple[int, str, bool]], current_chat_id: int | None = None, page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    """
    群组列表键盘

    Args:
        chats: [(chat_id, title, is_admin), ...]
        current_chat_id: 当前选中的群组ID
        page: 当前页码
        page_size: 每页显示数量
    """
    buttons = []
    start_idx = page * page_size
    end_idx = start_idx + page_size

    for chat_id, title, is_admin in chats[start_idx:end_idx]:
        is_current = chat_id == current_chat_id
        prefix = "✅ " if is_current else ""
        label = f"{prefix}{title}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"group:select:{chat_id}")])

    # 分页导航
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"group:list:{page-1}"))
    if end_idx < len(chats):
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"group:list:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    # 刷新按钮
    buttons.append([InlineKeyboardButton("🔄 刷新列表", callback_data="group:refresh")])

    return InlineKeyboardMarkup(buttons)
