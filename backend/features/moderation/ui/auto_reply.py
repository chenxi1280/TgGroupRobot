"""自动回复键盘

提供自动回复规则管理的键盘生成。
"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.ui.message_config_panel import action_button, button_count, mark_configured
from backend.shared.ui.base.helpers import create_back_button


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
    back_button = create_back_button(chat_id, "main")

    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 添加一条", callback_data=create_callback)],
        [InlineKeyboardButton("📋 规则列表", callback_data=list_callback)],
        [back_button],
    ])


def auto_reply_list_keyboard(
    rules: list,
    chat_id: int | None = None,
    page: int = 0,
    page_size: int = 8,
    total_count: int | None = None,
) -> InlineKeyboardMarkup:
    """自动回复规则列表键盘

    Args:
        rules: 自动回复规则列表
        chat_id: 群组 ID，用于在私聊中操作群组时指定目标群组
    """
    buttons = []
    total_items = total_count if total_count is not None else len(rules)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    current_page = min(max(page, 0), total_pages - 1)
    start_idx = current_page * page_size
    end_idx = start_idx + page_size
    page_rules = rules[start_idx:end_idx]

    for rule in page_rules:
        detail_callback = (
            f"auto_reply:detail:{chat_id}:{rule.id}"
            if chat_id is not None
            else f"auto_reply:detail::{rule.id}"
        )
        next_active = "0" if rule.is_active else "1"
        status_callback = (
            f"auto_reply:set:{chat_id}:{rule.id}:active:{next_active}"
            if chat_id is not None
            else f"auto_reply:toggle::{rule.id}"
        )
        delete_callback = (
            f"auto_reply:delete:{chat_id}:{rule.id}:confirm"
            if chat_id is not None
            else f"auto_reply:delete::{rule.id}:confirm"
        )

        buttons.append([
            InlineKeyboardButton(f"顺序 {rule.sort_order}", callback_data=detail_callback),
            InlineKeyboardButton("✅ 启用" if rule.is_active else "❌ 关闭", callback_data=status_callback),
            InlineKeyboardButton("修改 🔧", callback_data=detail_callback),
            InlineKeyboardButton("删除 🗑️", callback_data=delete_callback),
        ])

    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if current_page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    "⬅️ 上一页",
                    callback_data=f"auto_reply:list:{chat_id}:{current_page - 1}" if chat_id is not None else f"auto_reply:list::{current_page - 1}",
                )
            )
        nav_row.append(InlineKeyboardButton(f"📄 {current_page + 1}/{total_pages}", callback_data="_noop"))
        if current_page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    "下一页 ➡️",
                    callback_data=f"auto_reply:list:{chat_id}:{current_page + 1}" if chat_id is not None else f"auto_reply:list::{current_page + 1}",
                )
            )
        buttons.append(nav_row)

    create_callback = f"auto_reply:create:{chat_id}" if chat_id is not None else "auto_reply:create"
    buttons.append([InlineKeyboardButton("➕ 添加一条", callback_data=create_callback)])

    back_callback = (
        f"adm:menu:main:{chat_id}"
        if chat_id
        else "auto_reply:menu"
    )
    buttons.append([InlineKeyboardButton("🔙 返回", callback_data=back_callback)])

    return InlineKeyboardMarkup(buttons)


def auto_reply_detail_keyboard(rule, chat_id: int) -> InlineKeyboardMarkup:
    is_active = bool(getattr(rule, "is_active", False))
    match_type = getattr(rule, "match_type", "exact")
    status_on = "✅ 启用" if is_active else "启用"
    status_off = "关闭" if is_active else "✅ 关闭"
    match_exact = "✅ 等于" if match_type == "exact" else "等于"
    match_contains = "✅ 包含" if match_type == "contains" else "包含"
    delete_source_on = "✅ 删除" if getattr(rule, "delete_source", False) else "删除"
    delete_source_off = "保留" if getattr(rule, "delete_source", False) else "✅ 保留"
    keywords_configured = bool(getattr(rule, "keywords", None))
    cover_configured = bool(getattr(rule, "cover_media_file_id", None))
    content_configured = bool(str(getattr(rule, "reply_content", "") or "").strip())
    buttons_configured = button_count(getattr(rule, "buttons", None)) > 0
    delay_configured = int(getattr(rule, "delete_reply_delay_seconds", 0) or 0) > 0
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("状态：", callback_data=f"auto_reply:detail:{chat_id}:{rule.id}"),
            InlineKeyboardButton(status_on, callback_data=f"auto_reply:set:{chat_id}:{rule.id}:active:1"),
            InlineKeyboardButton(status_off, callback_data=f"auto_reply:set:{chat_id}:{rule.id}:active:0"),
        ],
        [
            InlineKeyboardButton("匹配：", callback_data=f"auto_reply:detail:{chat_id}:{rule.id}"),
            InlineKeyboardButton(match_exact, callback_data=f"auto_reply:set:{chat_id}:{rule.id}:match:exact"),
            InlineKeyboardButton(match_contains, callback_data=f"auto_reply:set:{chat_id}:{rule.id}:match:contains"),
        ],
        [
            InlineKeyboardButton("删除来源：", callback_data=f"auto_reply:detail:{chat_id}:{rule.id}"),
            InlineKeyboardButton(delete_source_on, callback_data=f"auto_reply:set:{chat_id}:{rule.id}:source:1"),
            InlineKeyboardButton(delete_source_off, callback_data=f"auto_reply:set:{chat_id}:{rule.id}:source:0"),
        ],
        [
            action_button("修改关键词", f"auto_reply:edit:{chat_id}:{rule.id}:keywords", configured=keywords_configured),
            action_button("修改封面", f"auto_reply:edit:{chat_id}:{rule.id}:cover", configured=cover_configured),
        ],
        [
            action_button("修改文本", f"auto_reply:edit:{chat_id}:{rule.id}:content", configured=content_configured),
            action_button("修改按钮", f"btned:open:auto_reply:{chat_id}:{rule.id}", configured=buttons_configured),
        ],
        [
            InlineKeyboardButton("🏖️ 预览效果", callback_data=f"auto_reply:preview:{chat_id}:{rule.id}"),
            InlineKeyboardButton(mark_configured("🕘 延迟删除", delay_configured), callback_data=f"auto_reply:delay:{chat_id}:{rule.id}"),
        ],
        [
            InlineKeyboardButton("❌ 删除配置", callback_data=f"auto_reply:delete:{chat_id}:{rule.id}:confirm"),
            InlineKeyboardButton("🔙 返回", callback_data=f"auto_reply:list:{chat_id}"),
        ],
    ])


def auto_reply_delay_keyboard(rule, chat_id: int) -> InlineKeyboardMarkup:
    current_delay = int(getattr(rule, "delete_reply_delay_seconds", 0) or 0)

    def label(seconds: int, text: str) -> str:
        return f"✅ {text}" if current_delay == seconds else text

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(label(15, "15秒"), callback_data=f"auto_reply:delay:set:{chat_id}:{rule.id}:15"),
            InlineKeyboardButton(label(30, "30秒"), callback_data=f"auto_reply:delay:set:{chat_id}:{rule.id}:30"),
            InlineKeyboardButton(label(60, "60秒"), callback_data=f"auto_reply:delay:set:{chat_id}:{rule.id}:60"),
            InlineKeyboardButton(label(90, "90秒"), callback_data=f"auto_reply:delay:set:{chat_id}:{rule.id}:90"),
        ],
        [
            InlineKeyboardButton(label(0, "不删除"), callback_data=f"auto_reply:delay:set:{chat_id}:{rule.id}:0"),
            InlineKeyboardButton("🔙 返回", callback_data=f"auto_reply:detail:{chat_id}:{rule.id}"),
        ],
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
