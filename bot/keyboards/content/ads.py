"""轮播广告键盘

提供轮播广告管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.base.helpers import create_back_button
from bot.keyboards.formatters import StatusIcons, format_schedule_info


def _format_ads_list_label(ad) -> str:
    status_icon = StatusIcons.enabled(ad.enabled)
    image_info = " 🖼️" if ad.has_image else ""

    if getattr(ad, "interval_hours", None):
        progress = ""
        if getattr(ad, "max_send_count", None):
            progress = f" {ad.send_count}/{ad.max_send_count}"
        return f"{status_icon} {ad.title} ⟳{ad.interval_hours}h{progress}{image_info}"

    schedule_info = format_schedule_info(
        getattr(ad, "schedule_time", None),
        getattr(ad, "frequency", None) or "单次",
        timezone_offset=8,
    )
    return f"{status_icon} {ad.title}{schedule_info}{image_info}"


def ads_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """轮播广告主菜单

    Args:
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    create_callback = f"ads:create:{chat_id}" if chat_id else "ads:create"
    back_button = create_back_button(chat_id, "back_to_menu")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 创建轮播广告", callback_data=create_callback)],
        [
            InlineKeyboardButton("📋 轮播列表", callback_data="ads:list"),
            InlineKeyboardButton("📊 轮播看板", callback_data="ads:stats"),
        ],
        [back_button],
    ])


def ads_list_keyboard(
    ads: list,
    chat_id: int | None = None,
    page: int = 0,
    page_size: int = 5,
) -> InlineKeyboardMarkup:
    """轮播广告列表键盘

    Args:
        ads: 广告列表
        chat_id: 群组 ID
        page: 当前页码
        page_size: 每页数量
    """
    buttons = []
    start_idx = page * page_size
    end_idx = start_idx + page_size

    for ad in ads[start_idx:end_idx]:
        label = _format_ads_list_label(ad)
        buttons.append([InlineKeyboardButton(label, callback_data=f"ads:detail:{ad.id}")])

    # 分页导航
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"ads:list:{page-1}"))
    if end_idx < len(ads):
        nav_buttons.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"ads:list:{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    back_callback = f"adm:back_to_menu:{chat_id}" if chat_id else "ads:menu"
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])
    return InlineKeyboardMarkup(buttons)


def ads_detail_keyboard(ad_id: int, is_enabled: bool) -> InlineKeyboardMarkup:
    """广告详情键盘"""
    buttons = []

    if is_enabled:
        buttons.append([
            InlineKeyboardButton("🔄 立即发送", callback_data=f"ads:send:{ad_id}"),
            InlineKeyboardButton("⏸️ 暂停", callback_data=f"ads:toggle:{ad_id}"),
        ])
    else:
        buttons.append([
            InlineKeyboardButton("▶️️ 启用", callback_data=f"ads:toggle:{ad_id}"),
        ])

    buttons.append([
        InlineKeyboardButton("🗑️ 删除", callback_data=f"ads:delete:{ad_id}"),
    ])

    buttons.append([InlineKeyboardButton("🔙 返回", callback_data="ads:list")])
    return InlineKeyboardMarkup(buttons)


def ads_create_keyboard() -> InlineKeyboardMarkup:
    """创建广告确认键盘"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 确认创建", callback_data="ads:create_confirm")],
        [InlineKeyboardButton("❌ 取消", callback_data="ads:menu")],
    ])


def ads_frequency_keyboard() -> InlineKeyboardMarkup:
    """推送频次选择键盘"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏰ 立即发送（单次）", callback_data="ads:freq:once")],
        [
            InlineKeyboardButton("📅 每天", callback_data="ads:freq:daily"),
            InlineKeyboardButton("📆 每周", callback_data="ads:freq:weekly"),
        ],
        [InlineKeyboardButton("🗓️ 每月", callback_data="ads:freq:monthly")],
        [InlineKeyboardButton("🔙 返回", callback_data="ads:menu")],
    ])
