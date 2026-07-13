"""接龙键盘

提供接龙管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.ui.base.helpers import create_back_button
from backend.shared.ui.formatters import StatusIcons, format_participant_count


def solitaire_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """接龙管理主菜单

    Args:
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    create_callback = f"sol:create:{chat_id}" if chat_id else "sol:create"
    list_callback = f"sol:list:{chat_id}:0" if chat_id else "sol:list"
    stats_callback = f"sol:stats:{chat_id}" if chat_id else "sol:stats"
    back_button = create_back_button(chat_id, "main")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 创建接龙", callback_data=create_callback)],
        [
            InlineKeyboardButton("📋 接龙列表", callback_data=list_callback),
            InlineKeyboardButton("📊 统计", callback_data=stats_callback),
        ],
        [back_button],
    ])


def solitaire_list_keyboard(
    solitaires: list,
    chat_id: int | None = None,
    page: int = 0,
    *, page_size: int = 5,
) -> InlineKeyboardMarkup:
    """接龙列表键盘

    Args:
        solitaires: 接龙列表
        chat_id: 群组 ID
        page: 当前页码
        page_size: 每页数量
    """
    buttons = []
    start_idx = page * page_size
    end_idx = start_idx + page_size

    for solitaire in solitaires[start_idx:end_idx]:
        # 使用 StatusIcons 获取状态图标
        icon_set = StatusIcons.for_solitaire()
        status_icon = icon_set.get(solitaire.status)

        # 使用 format_participant_count 格式化参与人数
        count = format_participant_count(
            len(solitaire.entries_rel),
            solitaire.max_participants,
        )

        label = f"{status_icon} {solitaire.title} {count}"

        # 在私聊场景下，包含 chat_id 参数
        detail_callback = f"sol:detail:{chat_id}:{solitaire.id}" if chat_id else f"sol:detail:{solitaire.id}"
        buttons.append([InlineKeyboardButton(label, callback_data=detail_callback)])

    # 分页导航
    nav_buttons = []
    if page > 0:
        prev_callback = f"sol:list:{chat_id}:{page-1}" if chat_id else f"sol:list:{page-1}"
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=prev_callback))
    if end_idx < len(solitaires):
        next_callback = f"sol:list:{chat_id}:{page+1}" if chat_id else f"sol:list:{page+1}"
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=next_callback))

    if nav_buttons:
        buttons.append(nav_buttons)

    back_callback = f"adm:menu:solitaire:{chat_id}" if chat_id else "sol:menu"
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)


def solitaire_detail_keyboard(
    solitaire_id: int,
    is_active: bool,
    chat_id: int | None = None,
) -> InlineKeyboardMarkup:
    """接龙详情键盘

    Args:
        solitaire_id: 接龙 ID
        is_active: 接龙是否活跃
        chat_id: 群组 ID
    """
    buttons = []

    if is_active:
        # 在私聊场景下，包含 chat_id 参数
        refresh_callback = f"sol:refresh:{chat_id}:{solitaire_id}" if chat_id else f"sol:refresh:{solitaire_id}"
        close_callback = f"sol:close:{chat_id}:{solitaire_id}" if chat_id else f"sol:close:{solitaire_id}"
        buttons.append([
            InlineKeyboardButton("🔄 刷新", callback_data=refresh_callback),
            InlineKeyboardButton("🔚 结束", callback_data=close_callback),
        ])

    delete_callback = f"sol:delete:{chat_id}:{solitaire_id}" if chat_id else f"sol:delete:{solitaire_id}"
    buttons.append([InlineKeyboardButton("🗑 删除", callback_data=delete_callback)])

    # 返回列表，在私聊场景下包含 chat_id 参数
    list_callback = f"sol:list:{chat_id}:0" if chat_id else "sol:list"
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=list_callback)])
    return InlineKeyboardMarkup(buttons)


def solitaire_create_keyboard() -> InlineKeyboardMarkup:
    """创建接龙确认键盘"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 确认创建", callback_data="sol:create_confirm")],
        [InlineKeyboardButton("❌ 取消", callback_data="sol:menu")],
    ])


def get_join_solitaire_keyboard(solitaire_id: int) -> InlineKeyboardMarkup:
    """获取参与接龙的键盘

    Args:
        solitaire_id: 接龙 ID

    Returns:
        参与接龙的按钮键盘
    """
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 参与接龙", callback_data=f"join_solitaire:{solitaire_id}")],
    ])
