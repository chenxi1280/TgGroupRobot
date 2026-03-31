"""自动回复键盘

提供自动回复规则管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.keyboards.base.helpers import create_back_button
from bot.keyboards.formatters import StatusIcons


def auto_reply_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    """自动回复菜单键盘

    Args:
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    create_callback = (
        f"auto_reply:create:{chat_id}"
        if chat_id
        else "auto_reply:create"
    )
    list_callback = (
        f"auto_reply:list:{chat_id}"
        if chat_id
        else "auto_reply:list"
    )
    back_button = create_back_button(chat_id, "back_to_menu")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 创建自动回复", callback_data=create_callback)],
        [InlineKeyboardButton("📋 规则列表", callback_data=list_callback)],
        [back_button],
    ])


def auto_reply_list_keyboard(
    rules: list,
    chat_id: int | None = None,
) -> InlineKeyboardMarkup:
    """自动回复规则列表键盘

    Args:
        rules: 自动回复规则列表
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    buttons = []

    for rule in rules:
        status_icon = StatusIcons.active(rule.is_active)
        label = f"{status_icon} #{rule.sort_order} [{rule.id}]"
        detail_callback = (
            f"auto_reply:detail:{chat_id}:{rule.id}"
            if chat_id is not None
            else f"auto_reply:detail::{rule.id}"
        )
        toggle_callback = (
            f"auto_reply:toggle:{chat_id}:{rule.id}"
            if chat_id is not None
            else f"auto_reply:toggle::{rule.id}"
        )
        up_callback = (
            f"auto_reply:move:{chat_id}:{rule.id}:up"
            if chat_id is not None
            else f"auto_reply:move::{rule.id}:up"
        )
        down_callback = (
            f"auto_reply:move:{chat_id}:{rule.id}:down"
            if chat_id is not None
            else f"auto_reply:move::{rule.id}:down"
        )
        preview_callback = (
            f"auto_reply:preview:{chat_id}:{rule.id}"
            if chat_id is not None
            else f"auto_reply:preview::{rule.id}"
        )
        delete_callback = (
            f"auto_reply:delete:{chat_id}:{rule.id}:confirm"
            if chat_id is not None
            else f"auto_reply:delete::{rule.id}:confirm"
        )

        buttons.append([InlineKeyboardButton(label, callback_data=detail_callback)])
        buttons.append([
            InlineKeyboardButton("⬆️", callback_data=up_callback),
            InlineKeyboardButton("⬇️", callback_data=down_callback),
            InlineKeyboardButton("👁️ 预览", callback_data=preview_callback),
            InlineKeyboardButton("⏯️", callback_data=toggle_callback),
            InlineKeyboardButton("🗑️", callback_data=delete_callback),
        ])

    # 返回按钮
    back_callback = (
        f"adm:menu:autoreply:{chat_id}"
        if chat_id
        else "auto_reply:menu"
    )
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])

    return InlineKeyboardMarkup(buttons)


def auto_reply_detail_keyboard(rule, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "👁️ 预览效果",
                callback_data=f"auto_reply:preview:{chat_id}:{rule.id}",
            ),
            InlineKeyboardButton(
                "⏯️ 切换状态",
                callback_data=f"auto_reply:toggle:{chat_id}:{rule.id}",
            ),
        ],
        [
            InlineKeyboardButton("🧩 关键词", callback_data=f"auto_reply:edit:{chat_id}:{rule.id}:keywords"),
            InlineKeyboardButton("✏️ 回复内容", callback_data=f"auto_reply:edit:{chat_id}:{rule.id}:content"),
        ],
        [
            InlineKeyboardButton("🖼️ 封面", callback_data=f"auto_reply:edit:{chat_id}:{rule.id}:cover"),
            InlineKeyboardButton("🔘 按钮", callback_data=f"auto_reply:edit:{chat_id}:{rule.id}:buttons"),
        ],
        [
            InlineKeyboardButton("🧠 匹配方式", callback_data=f"auto_reply:cycle:{chat_id}:{rule.id}:match"),
            InlineKeyboardButton("🔤 大小写", callback_data=f"auto_reply:togglecfg:{chat_id}:{rule.id}:case"),
        ],
        [
            InlineKeyboardButton("🧹 删来源", callback_data=f"auto_reply:togglecfg:{chat_id}:{rule.id}:source"),
            InlineKeyboardButton("⏱️ 延迟删除", callback_data=f"auto_reply:cycle:{chat_id}:{rule.id}:delay"),
        ],
        [
            InlineKeyboardButton("⬆️ 上移", callback_data=f"auto_reply:move:{chat_id}:{rule.id}:up"),
            InlineKeyboardButton("⬇️ 下移", callback_data=f"auto_reply:move:{chat_id}:{rule.id}:down"),
        ],
        [InlineKeyboardButton("🗑️ 删除规则", callback_data=f"auto_reply:delete:{chat_id}:{rule.id}:confirm")],
        [InlineKeyboardButton("🔙 返回列表", callback_data=f"auto_reply:list:{chat_id}")],
    ])


def auto_reply_delete_confirm_keyboard(rule_id: int, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 确认删除", callback_data=f"auto_reply:delete:{chat_id}:{rule_id}:do"),
            InlineKeyboardButton("取消", callback_data=f"auto_reply:detail:{chat_id}:{rule_id}"),
        ],
    ])


def auto_reply_preview_keyboard(rule_id: int, chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 返回规则详情", callback_data=f"auto_reply:detail:{chat_id}:{rule_id}")],
    ])
