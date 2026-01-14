"""群组选择键盘

提供群组列表和选择相关的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardMarkup

from bot.keyboards.base.builders import KeyboardBuilder


def chat_group_list_keyboard(
    chats: list[tuple[int, str, bool]],
    current_chat_id: int | None = None,
    page: int = 0,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    """群组列表键盘

    Args:
        chats: 群组列表，格式为 [(chat_id, title, is_admin), ...]
        current_chat_id: 当前选中的群组 ID
        page: 当前页码
        page_size: 每页显示数量

    Returns:
        群组列表键盘
    """
    builder = KeyboardBuilder("group")

    # 添加群组列表项
    start_idx = page * page_size
    end_idx = start_idx + page_size

    for chat_id, title, is_admin in chats[start_idx:end_idx]:
        is_current = chat_id == current_chat_id
        prefix = "✅ " if is_current else ""
        label = f"{prefix}{title}"
        builder.add_button(label, "select", chat_id)

    # 添加分页导航
    builder.add_pagination(page, len(chats), page_size, "list")

    # 添加刷新按钮
    builder.add_button("🔄 刷新列表", "refresh")

    return builder.build()
