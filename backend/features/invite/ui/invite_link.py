"""邀请链接键盘

提供邀请链接管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.ui.base.helpers import create_back_button
from backend.shared.ui.formatters import StatusIcons, format_range
from backend.shared.ui.message_config_panel import action_button


def _toggle_labels(enabled: bool) -> tuple[str, str]:
    return ("✅ 启动", "关闭") if enabled else ("启动", "❌ 关闭")


def invite_link_menu_keyboard(
    chat_id: int | None = None,
    *,
    enabled: bool = True,
    remind_enabled: bool = True,
    mode: str = "direct",
    has_cover: bool = False,
    text_configured: bool = False,
    button_rows: int = 0,
) -> InlineKeyboardMarkup:
    """邀请链接管理主菜单

    Args:
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    enabled_on, enabled_off = _toggle_labels(enabled)
    remind_on, remind_off = _toggle_labels(remind_enabled)
    back_button = create_back_button(chat_id, "main")
    relay_label = "✅ 中转" if mode == "relay" else "中转"
    direct_label = "✅ 直接" if mode == "direct" else "直接"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("状态:", callback_data=f"inv:home:{chat_id}" if chat_id else "inv:menu"),
            InlineKeyboardButton(enabled_on, callback_data=f"inv:toggle:enabled:{chat_id}:1" if chat_id else "inv:toggle:enabled"),
            InlineKeyboardButton(enabled_off, callback_data=f"inv:toggle:enabled:{chat_id}:0" if chat_id else "inv:toggle:enabled"),
        ],
        [
            InlineKeyboardButton("邀请提醒:", callback_data=f"inv:home:{chat_id}" if chat_id else "inv:menu"),
            InlineKeyboardButton(remind_on, callback_data=f"inv:toggle:remind:{chat_id}:1" if chat_id else "inv:toggle:remind"),
            InlineKeyboardButton(remind_off, callback_data=f"inv:toggle:remind:{chat_id}:0" if chat_id else "inv:toggle:remind"),
        ],
        [
            InlineKeyboardButton("模式:", callback_data=f"inv:home:{chat_id}" if chat_id else "inv:menu"),
            InlineKeyboardButton(relay_label, callback_data=f"inv:mode:{chat_id}:relay" if chat_id else "inv:mode:relay"),
            InlineKeyboardButton(direct_label, callback_data=f"inv:mode:{chat_id}:direct" if chat_id else "inv:mode:direct"),
        ],
        [
            action_button("设置封面", f"inv:cover:{chat_id}" if chat_id else "inv:cover", configured=has_cover),
            action_button("设置文本", f"inv:text:{chat_id}" if chat_id else "inv:text", configured=text_configured),
        ],
        [
            action_button("设置按钮", f"inv:buttons:{chat_id}" if chat_id else "inv:buttons", configured=button_rows > 0),
            InlineKeyboardButton("👀 预览效果", callback_data=f"inv:preview:{chat_id}" if chat_id else "inv:preview"),
        ],
        [
            InlineKeyboardButton("🧹 清零统计", callback_data=f"inv:reset:count:{chat_id}" if chat_id else "inv:reset:count"),
            InlineKeyboardButton("♻️ 清空链接", callback_data=f"inv:reset:links:{chat_id}" if chat_id else "inv:reset:links"),
        ],
        [InlineKeyboardButton("📤 导出数据", callback_data=f"inv:export:{chat_id}" if chat_id else "inv:export")],
        [back_button],
    ])


def invite_link_list_keyboard(
    links: list,
    chat_id: int | None = None,
    page: int = 0,
    *, page_size: int = 5,
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

        callback = f"inv:detail:{link.id}:{chat_id}" if chat_id else f"inv:detail:{link.id}"
        buttons.append([InlineKeyboardButton(label, callback_data=callback)])

    # 分页导航
    nav_buttons = []
    if page > 0:
        callback = f"inv:list:{page-1}:{chat_id}" if chat_id else f"inv:list:{page-1}"
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=callback))
    if end_idx < len(links):
        callback = f"inv:list:{page+1}:{chat_id}" if chat_id else f"inv:list:{page+1}"
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=callback))

    if nav_buttons:
        buttons.append(nav_buttons)

    back_callback = f"inv:home:{chat_id}" if chat_id else "inv:menu"
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)


def invite_link_detail_keyboard(link_id: int, chat_id: int | None = None) -> InlineKeyboardMarkup:
    """邀请链接详情键盘"""
    refresh_callback = f"inv:refresh:{link_id}:{chat_id}" if chat_id else f"inv:refresh:{link_id}"
    revoke_callback = f"inv:revoke:{link_id}:{chat_id}" if chat_id else f"inv:revoke:{link_id}"
    delete_callback = f"inv:delete:{link_id}:{chat_id}" if chat_id else f"inv:delete:{link_id}"
    back_callback = f"inv:list:0:{chat_id}" if chat_id else "inv:list"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 刷新", callback_data=refresh_callback),
            InlineKeyboardButton("❌ 撤销", callback_data=revoke_callback),
        ],
        [InlineKeyboardButton("🗑 删除", callback_data=delete_callback)],
        [InlineKeyboardButton("🔙 返回", callback_data=back_callback)],
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
