from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.models.enums import SolitaireStatus


def solitaire_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """接龙管理主菜单

    Args:
        chat_id: 群组ID，用于在私聊中操作群组时指定目标群组
    """
    back_callback = f"adm:back_to_menu:{chat_id}" if chat_id else "adm:menu:main"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ 创建接龙", callback_data="sol:create"),
        ],
        [
            InlineKeyboardButton("📋 接龙列表", callback_data="sol:list"),
            InlineKeyboardButton("📊 统计", callback_data="sol:stats"),
        ],
        [
            InlineKeyboardButton("🔙 返回", callback_data=back_callback),
        ],
    ])


def solitaire_list_keyboard(solitaires: list, chat_id: int | None = None, page: int = 0, page_size: int = 5) -> InlineKeyboardMarkup:
    """接龙列表键盘

    Args:
        solitaires: 接龙列表
        chat_id: 群组ID，用于在私聊中操作群组时指定目标群组
        page: 当前页码
        page_size: 每页数量
    """
    buttons = []
    start_idx = page * page_size
    end_idx = start_idx + page_size

    for solitaire in solitaires[start_idx:end_idx]:
        status_emoji = {
            SolitaireStatus.active.value: "🟢",
            SolitaireStatus.closed.value: "🔴",
        }.get(solitaire.status, "⚪")

        count = f"({len(solitaire.entries)}"
        if solitaire.max_participants:
            count += f"/{solitaire.max_participants}"
        count += "人)"

        label = f"{status_emoji} {solitaire.title} {count}"

        buttons.append([InlineKeyboardButton(label, callback_data=f"sol:detail:{solitaire.id}")])

    # 分页导航
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"sol:list:{page-1}"))
    if end_idx < len(solitaires):
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"sol:list:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    back_callback = f"adm:back_to_menu:{chat_id}" if chat_id else "sol:menu"
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)


def solitaire_detail_keyboard(solitaire_id: int, is_active: bool) -> InlineKeyboardMarkup:
    """接龙详情键盘"""
    buttons = []

    if is_active:
        buttons.append([
            InlineKeyboardButton("🔄 刷新", callback_data=f"sol:refresh:{solitaire_id}"),
            InlineKeyboardButton("🔚 结束", callback_data=f"sol:close:{solitaire_id}"),
        ])

    buttons.append([
        InlineKeyboardButton("🗑 删除", callback_data=f"sol:delete:{solitaire_id}"),
    ])

    buttons.append([InlineKeyboardButton("🔙 返回", callback_data="sol:list")])
    return InlineKeyboardMarkup(buttons)


def solitaire_create_keyboard() -> InlineKeyboardMarkup:
    """创建接龙确认键盘"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 确认创建", callback_data="sol:create_confirm"),
        ],
        [
            InlineKeyboardButton("❌ 取消", callback_data="sol:menu"),
        ],
    ])
