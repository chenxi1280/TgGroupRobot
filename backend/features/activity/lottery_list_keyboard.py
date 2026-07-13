from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _activity_filter_rows(chat_id: int, status: str, lottery_type: str):
    return [
        [
            InlineKeyboardButton(
                "✅ 全部" if status == "all" else "全部",
                callback_data=f"lot:list:{chat_id}:all:{lottery_type}:0",
            ),
            InlineKeyboardButton(
                "✅ 待开奖" if status == "pending" else "待开奖",
                callback_data=f"lot:list:{chat_id}:pending:{lottery_type}:0",
            ),
            InlineKeyboardButton(
                "✅ 已开奖" if status == "completed" else "已开奖",
                callback_data=f"lot:list:{chat_id}:completed:{lottery_type}:0",
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ 全部类型" if lottery_type == "all" else "全部类型",
                callback_data=f"lot:list:{chat_id}:{status}:all:0",
            ),
            InlineKeyboardButton(
                "🎁 通用", callback_data=f"lot:list:{chat_id}:{status}:common:0"
            ),
            InlineKeyboardButton(
                "💰 积分", callback_data=f"lot:list:{chat_id}:{status}:points:0"
            ),
            InlineKeyboardButton(
                "📣 关注", callback_data=f"lot:list:{chat_id}:{status}:subscribe:0"
            ),
        ],
        [
            InlineKeyboardButton(
                "👥 邀请", callback_data=f"lot:list:{chat_id}:{status}:invite:0"
            ),
            InlineKeyboardButton(
                "🔥 活跃", callback_data=f"lot:list:{chat_id}:{status}:activity:0"
            ),
        ],
    ]


def _activity_navigation_row(
    *, chat_id: int, status: str, lottery_type: str, page: int, has_next: bool
):
    row = []
    if page > 0:
        row.append(
            InlineKeyboardButton(
                "⬅️ 上一页",
                callback_data=f"lot:list:{chat_id}:{status}:{lottery_type}:{page - 1}",
            )
        )
    if has_next:
        row.append(
            InlineKeyboardButton(
                "下一页 ➡️",
                callback_data=f"lot:list:{chat_id}:{status}:{lottery_type}:{page + 1}",
            )
        )
    return row


def build_activity_list_keyboard(
    subset,
    *,
    chat_id: int,
    status: str,
    lottery_type: str,
    page: int,
    has_next: bool,
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"🔎 #{item.id} {item.title[:16]}",
                callback_data=f"lot:detail:{chat_id}:{item.id}",
            )
        ]
        for item in subset
    ]
    rows.extend(_activity_filter_rows(chat_id, status, lottery_type))
    nav_row = _activity_navigation_row(
        chat_id=chat_id,
        status=status,
        lottery_type=lottery_type,
        page=page,
        has_next=has_next,
    )
    if nav_row:
        rows.append(nav_row)
    rows.append(
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:lottery:{chat_id}")]
    )
    return InlineKeyboardMarkup(rows)
