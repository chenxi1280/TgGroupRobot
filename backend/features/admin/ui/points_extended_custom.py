from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _bool_label(enabled: bool, true_label: str, false_label: str) -> str:
    return f"✅ {true_label}" if enabled else f"❌ {false_label}"


def custom_points_list_keyboard(items, chat_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        rows.append(
            [
                InlineKeyboardButton(f"🔢 编号:{item.type_no}", callback_data=f"adm:cpt:{chat_id}:detail:{item.id}"),
                InlineKeyboardButton(_bool_label(bool(item.enabled), "启用", "关闭"), callback_data=f"adm:cpt:{chat_id}:toggle:{item.id}:{0 if item.enabled else 1}"),
                InlineKeyboardButton("✏️ 修改", callback_data=f"adm:cpt:{chat_id}:edit:name:{item.id}"),
                InlineKeyboardButton("🗑 删除", callback_data=f"adm:cpt:{chat_id}:delete_confirm:{item.id}"),
            ]
        )
    rows.append([InlineKeyboardButton("➕ 添加一条", callback_data=f"adm:cpt:{chat_id}:add")])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:points:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def custom_point_detail_keyboard(item, chat_id: int) -> InlineKeyboardMarkup:
    enabled = bool(item.enabled)
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:cpt:{chat_id}:noop:{item.id}"),
                InlineKeyboardButton("✅ 启动" if enabled else "启动", callback_data=f"adm:cpt:{chat_id}:toggle:{item.id}:1"),
                InlineKeyboardButton("关闭" if enabled else "❌ 关闭", callback_data=f"adm:cpt:{chat_id}:toggle:{item.id}:0"),
            ],
            [
                InlineKeyboardButton("🏷️ 积分名字：", callback_data=f"adm:cpt:{chat_id}:noop:{item.id}"),
                InlineKeyboardButton(item.name, callback_data=f"adm:cpt:{chat_id}:edit:name:{item.id}"),
            ],
            [
                InlineKeyboardButton("🥇 排行指令：", callback_data=f"adm:cpt:{chat_id}:noop:{item.id}"),
                InlineKeyboardButton(item.rank_command or "待配置", callback_data=f"adm:cpt:{chat_id}:edit:rank:{item.id}"),
            ],
            [
                InlineKeyboardButton("➕ 增加积分", callback_data=f"adm:cpt:{chat_id}:adjust:add:{item.id}"),
                InlineKeyboardButton("➖ 扣除积分", callback_data=f"adm:cpt:{chat_id}:adjust:deduct:{item.id}"),
            ],
            [
                InlineKeyboardButton("📤 导出操作日志", callback_data=f"adm:cpt:{chat_id}:export:{item.id}"),
                InlineKeyboardButton("🧹 清空此积分", callback_data=f"adm:cpt:{chat_id}:clear_confirm:{item.id}"),
            ],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:custom_points:{chat_id}")],
        ]
    )
