from __future__ import annotations

from backend.shared.ui.admin_keyboard import admin_keyboard
from backend.shared.ui.menu_layout import page_navigation, navigation_row

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _bool_label(enabled: bool, true_label: str, false_label: str) -> str:
    return f"✅ {true_label}" if enabled else f"❌ {false_label}"


def custom_points_list_keyboard(items, chat_id: int, *, page: int = 0, total: int | None = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"#{item.id} {item.name[:22]} · {'✓' if item.enabled else '○'}",
                                  callback_data=f"adm:cpt:{chat_id}:detail:{item.id}")] for item in items]
    rows.extend(page_navigation(page, len(items) if total is None else total,
                                lambda value: f"adm:cpt:{chat_id}:page:{value}"))
    rows.append([InlineKeyboardButton("添加积分类型", callback_data=f"adm:cpt:{chat_id}:add")])
    rows.append(navigation_row(f"adm:menu:category_growth:{chat_id}", refresh=f"adm:cpt:{chat_id}:page:{page}"))
    return InlineKeyboardMarkup(rows)


def custom_point_detail_keyboard(item, chat_id: int) -> InlineKeyboardMarkup:
    enabled = bool(item.enabled)
    return admin_keyboard(
        [
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"adm:cpt:{chat_id}:noop:{item.id}"),
                InlineKeyboardButton("✅ 启动" if enabled else "启动", callback_data=f"adm:cpt:{chat_id}:toggle:{item.id}:1"),
                InlineKeyboardButton("关闭" if enabled else "❌ 关闭", callback_data=f"adm:cpt:{chat_id}:toggle:{item.id}:0"),
            ],
            [
                InlineKeyboardButton("🏷️ 积分名字：", callback_data=f"adm:cpt:{chat_id}:noop:{item.id}"),
                InlineKeyboardButton("修改名称", callback_data=f"adm:cpt:{chat_id}:edit:name:{item.id}"),
            ],
            [
                InlineKeyboardButton("🥇 排行指令：", callback_data=f"adm:cpt:{chat_id}:noop:{item.id}"),
                InlineKeyboardButton("修改指令", callback_data=f"adm:cpt:{chat_id}:edit:rank:{item.id}"),
            ],
            [
                InlineKeyboardButton("➕ 增加积分", callback_data=f"adm:cpt:{chat_id}:adjust:add:{item.id}"),
                InlineKeyboardButton("➖ 扣除积分", callback_data=f"adm:cpt:{chat_id}:adjust:deduct:{item.id}"),
            ],
            [
                InlineKeyboardButton("📤 导出操作日志", callback_data=f"adm:cpt:{chat_id}:export:{item.id}"),
            ],
            [
                InlineKeyboardButton("🧹 清空此积分", callback_data=f"adm:cpt:{chat_id}:clear_confirm:{item.id}"),
            ],
            [InlineKeyboardButton("删除积分类型", callback_data=f"adm:cpt:{chat_id}:delete_confirm:{item.id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:custom_points:{chat_id}")],
        ]
    )
