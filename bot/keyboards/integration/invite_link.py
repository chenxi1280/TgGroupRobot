"""邀请链接键盘

提供邀请链接管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.base.helpers import create_back_button
from bot.keyboards.formatters import StatusIcons, format_range


def invite_link_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """邀请链接管理主菜单

    Args:
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    create_callback = f"inv:create:{chat_id}" if chat_id else "inv:create"
    back_button = create_back_button(chat_id, "back_to_menu")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 创建邀请链接", callback_data=create_callback)],
        [
            InlineKeyboardButton("📋 链接列表", callback_data="inv:list"),
            InlineKeyboardButton("📊 统计", callback_data="inv:stats"),
        ],
        [back_button],
    ])


def invite_link_list_keyboard(
    links: list,
    chat_id: int | None = None,
    page: int = 0,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    """邀请链接列表键盘

    Args:
        links: 邀请链接列表
        chat_id: 群组 ID
        page: 当前页码
        page_size: 每页数量
    """
    buttons = []
    start_idx = page * page_size
    end_idx = start_idx + page_size

    for link in links[start_idx:end_idx]:
        # 使用 StatusIcons 获取状态图标
        icon_set = StatusIcons.for_invite_links()
        status_icon = icon_set.get(link.status)

        name = link.name or "未命名"
        limit = format_range(link.member_count, link.member_limit) if link.member_limit else f"({link.member_count})"
        label = f"{status_icon} {name} {limit}"

        buttons.append([InlineKeyboardButton(label, callback_data=f"inv:detail:{link.id}")])

    # 分页导航
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"inv:list:{page-1}"))
    if end_idx < len(links):
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"inv:list:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    back_callback = f"adm:back_to_menu:{chat_id}" if chat_id else "inv:menu"
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)


def invite_link_detail_keyboard(link_id: int) -> InlineKeyboardMarkup:
    """邀请链接详情键盘"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 刷新", callback_data=f"inv:refresh:{link_id}"),
            InlineKeyboardButton("❌ 撤销", callback_data=f"inv:revoke:{link_id}"),
        ],
        [InlineKeyboardButton("🗑 删除", callback_data=f"inv:delete:{link_id}")],
        [InlineKeyboardButton("🔙 返回", callback_data="inv:list")],
    ])


def invite_link_create_keyboard() -> InlineKeyboardMarkup:
    """创建邀请链接确认键盘"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 确认创建", callback_data="inv:create_confirm")],
        [InlineKeyboardButton("❌ 取消", callback_data="inv:menu")],
    ])


def user_invite_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    """用户邀请链接菜单"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 生成链接", callback_data=f"inv:user:create:{chat_id}")],
        [
            InlineKeyboardButton("📋 我的链接", callback_data=f"inv:user:list:{chat_id}"),
            InlineKeyboardButton("🏆 邀请排行", callback_data=f"inv:user:rank:{chat_id}"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"inv:user:menu:{chat_id}")],
    ])
