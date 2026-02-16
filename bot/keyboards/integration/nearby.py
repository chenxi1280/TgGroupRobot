from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def nearby_manage_keyboard(chat_id: int, is_visible: bool) -> InlineKeyboardMarkup:
    visible_label = "🙈 隐藏我的位置" if is_visible else "👁️ 显示我的位置"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📍 更新实时定位", callback_data=f"lbs:set:{chat_id}:location")],
            [
                InlineKeyboardButton("💰 修改价格", callback_data=f"lbs:set:{chat_id}:price"),
                InlineKeyboardButton("📦 修改方式", callback_data=f"lbs:set:{chat_id}:method"),
            ],
            [InlineKeyboardButton("🏠 修改备注", callback_data=f"lbs:set:{chat_id}:address")],
            [InlineKeyboardButton(visible_label, callback_data=f"lbs:toggle:{chat_id}")],
            [InlineKeyboardButton("🗑️ 清空资料", callback_data=f"lbs:clear:{chat_id}:confirm")],
            [
                InlineKeyboardButton("📍 查看周边", callback_data=f"lbs:list:{chat_id}:0"),
                InlineKeyboardButton("❌ 关闭", callback_data="lbs:close"),
            ],
        ]
    )


def nearby_clear_confirm_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ 确认清空", callback_data=f"lbs:clear:{chat_id}:do"),
                InlineKeyboardButton("❌ 取消", callback_data=f"lbs:clear:{chat_id}:cancel"),
            ]
        ]
    )


def nearby_list_keyboard(
    chat_id: int,
    member_buttons: list[tuple[str, int]],
    *,
    page: int,
    has_prev: bool,
    has_next: bool,
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []

    for label, user_id in member_buttons:
        buttons.append(
            [InlineKeyboardButton(f"🔍 查看 {label} 的详情", callback_data=f"lbs:detail:{chat_id}:{user_id}:{page}")]
        )

    nav_row: list[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"lbs:list:{chat_id}:{page-1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"lbs:list:{chat_id}:{page+1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append(
        [
            InlineKeyboardButton("🔄 刷新列表", callback_data=f"lbs:refresh:{chat_id}:{page}"),
            InlineKeyboardButton("❌ 关闭", callback_data="lbs:close"),
        ]
    )

    return InlineKeyboardMarkup(buttons)


def nearby_detail_keyboard(chat_id: int, user_id: int, back_page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💬 发起私聊", url=f"tg://user?id={user_id}")],
            [
                InlineKeyboardButton("⭐ 收藏", callback_data=f"lbs:fav:{chat_id}:{user_id}"),
                InlineKeyboardButton("🚩 举报", callback_data=f"lbs:report:{chat_id}:{user_id}"),
            ],
            [InlineKeyboardButton("🔙 返回列表", callback_data=f"lbs:list:{chat_id}:{back_page}")],
        ]
    )

