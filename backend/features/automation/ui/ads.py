"""轮播广告界面键盘。"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.features.automation.services.ad_rotation_service import (
    describe_delete_policy,
    format_interval_seconds_label,
)
from backend.shared.time_ui import build_back_keyboard, build_interval_keyboard
from backend.shared.ui.message_config_panel import action_button, button_count, mark_configured
from backend.shared.ui.base.helpers import create_back_button


def ads_menu_keyboard(chat_id: int | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("轮播规则设置", callback_data=f"ads:rules:{chat_id}" if chat_id else "ads:rules"),
            InlineKeyboardButton("轮播广告管理", callback_data=f"ads:list:{chat_id}:0" if chat_id else "ads:list:0"),
        ],
        [
            InlineKeyboardButton("📜 派发历史", callback_data=f"ads:history:{chat_id}:all"),
        ],
        [create_back_button(chat_id, "main")],
    ])


def ads_rules_keyboard(chat_id: int, rule) -> InlineKeyboardMarkup:
    enabled_on = "✅ 启动" if rule.enabled else "启动"
    enabled_off = "关闭" if rule.enabled else "✅ 关闭"
    mode_send = "✅ 发送" if rule.mode == "send" else "发送"
    mode_send_pin = "✅ 发送+置顶" if rule.mode == "send_pin" else "发送+置顶"
    unpin_on = "✅ 开启" if rule.unpin_previous else "开启"
    unpin_off = "关闭" if rule.unpin_previous else "✅ 关闭"

    delete_none = "✅ 不删" if rule.delete_policy == "none" else "不删"
    delete_prev = "✅ 删上条" if rule.delete_policy == "delete_prev" else "删上条"
    delete_prev_cycle = "✅ 删上轮" if rule.delete_policy == "delete_prev_cycle" else "删上轮"
    delete_delay = "✅ 延迟删" if rule.delete_policy == "delete_delay" else "延迟删"

    interval_label = format_interval_seconds_label(getattr(rule, "interval_seconds", 7200))

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("状态：", callback_data=f"ads:rules:{chat_id}"),
            InlineKeyboardButton(enabled_on, callback_data=f"ads:rules:set:{chat_id}:enabled:1"),
            InlineKeyboardButton(enabled_off, callback_data=f"ads:rules:set:{chat_id}:enabled:0"),
        ],
        [
            InlineKeyboardButton("轮播方式：", callback_data=f"ads:rules:{chat_id}"),
            InlineKeyboardButton(mode_send, callback_data=f"ads:rules:set:{chat_id}:mode:send"),
            InlineKeyboardButton(mode_send_pin, callback_data=f"ads:rules:set:{chat_id}:mode:send_pin"),
        ],
        [
            InlineKeyboardButton("起始时间", callback_data=f"ads:rules:input:{chat_id}:start"),
            InlineKeyboardButton(f"轮播间隔（{interval_label}）", callback_data=f"ads:rules:input:{chat_id}:interval"),
        ],
        [InlineKeyboardButton("·取消上一条置顶·", callback_data=f"ads:rules:hint:{chat_id}:unpin_previous")],
        [
            InlineKeyboardButton(unpin_on, callback_data=f"ads:rules:set:{chat_id}:unpin_previous:1"),
            InlineKeyboardButton(unpin_off, callback_data=f"ads:rules:set:{chat_id}:unpin_previous:0"),
        ],
        [InlineKeyboardButton("·删除轮播规则·", callback_data=f"ads:rules:{chat_id}")],
        [
            InlineKeyboardButton(delete_none, callback_data=f"ads:rules:set:{chat_id}:delete_policy:none"),
            InlineKeyboardButton(delete_prev, callback_data=f"ads:rules:set:{chat_id}:delete_policy:delete_prev"),
            InlineKeyboardButton(delete_prev_cycle, callback_data=f"ads:rules:set:{chat_id}:delete_policy:delete_prev_cycle"),
            InlineKeyboardButton(delete_delay, callback_data=f"ads:rules:set:{chat_id}:delete_policy:delete_delay"),
        ],
        [
            InlineKeyboardButton("🎯 置顶池", callback_data=f"ads:pool:top:{chat_id}"),
            InlineKeyboardButton("🚫 排除池", callback_data=f"ads:pool:exclude:{chat_id}"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"ads:menu:{chat_id}")],
    ])


def ads_manage_keyboard(chat_id: int, item, *, page: int, total_pages: int) -> InlineKeyboardMarkup:
    status_label = "✅ 启用" if item.enabled else "❌ 关闭"
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(f"顺序: {item.sort_order}", callback_data=f"ads:item:input:{chat_id}:{item.id}:order"),
            InlineKeyboardButton(status_label, callback_data=f"ads:item:toggle:{chat_id}:{item.id}"),
            InlineKeyboardButton("修改", callback_data=f"ads:detail:{chat_id}:{item.id}"),
            InlineKeyboardButton("删除", callback_data=f"ads:item:delete:{chat_id}:{item.id}"),
        ],
        [
            InlineKeyboardButton("➕ 添加一条", callback_data=f"ads:create:{chat_id}"),
            InlineKeyboardButton("➖ 过期清理", callback_data=f"ads:cleanup:{chat_id}"),
        ],
    ]
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️ 上一页", callback_data=f"ads:list:{chat_id}:{page-1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("下一页 ➡️", callback_data=f"ads:list:{chat_id}:{page+1}"))
        if nav_row:
            rows.append(nav_row)
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"ads:menu:{chat_id}")])
    return InlineKeyboardMarkup(rows)


def ads_item_detail_keyboard(chat_id: int, item, rule=None) -> InlineKeyboardMarkup:
    title_configured = bool(str(getattr(item, "title", "") or "").strip())
    cover_configured = bool(getattr(item, "image_file_id", None))
    text_configured = bool(str(getattr(item, "content", "") or "").strip())
    buttons_configured = button_count(getattr(item, "buttons", None)) > 0
    time_configured = bool(getattr(item, "start_time", None) or getattr(item, "end_time", None))
    enabled_on = "✅ 启用" if item.enabled else "启用"
    enabled_off = "关闭" if item.enabled else "✅ 关闭"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("状态：", callback_data=f"ads:detail:{chat_id}:{item.id}"),
            InlineKeyboardButton(enabled_on, callback_data=f"ads:item:set:{chat_id}:{item.id}:enabled:1"),
            InlineKeyboardButton(enabled_off, callback_data=f"ads:item:set:{chat_id}:{item.id}:enabled:0"),
        ],
        [
            action_button("标题备注", f"ads:item:input:{chat_id}:{item.id}:title", configured=title_configured),
            action_button("设置封面", f"ads:item:input:{chat_id}:{item.id}:cover", configured=cover_configured),
        ],
        [
            action_button("设置文本", f"ads:item:input:{chat_id}:{item.id}:text", configured=text_configured),
            action_button("设置按钮", f"btned:open:ads:{chat_id}:{item.id}", configured=buttons_configured),
        ],
        [
            action_button("时间范围", f"ads:item:time:{chat_id}:{item.id}", configured=time_configured),
            InlineKeyboardButton(
                f"发送频率：{format_interval_seconds_label(getattr(rule, 'interval_seconds', 7200))}" if rule else "发送频率",
                callback_data=f"ads:rules:input:{chat_id}:interval",
            ),
        ],
        [
            InlineKeyboardButton("🏖️ 预览效果", callback_data=f"ads:item:preview:{chat_id}:{item.id}"),
            InlineKeyboardButton("🔁 轮播顺序", callback_data=f"ads:item:input:{chat_id}:{item.id}:order"),
        ],
        [
            InlineKeyboardButton("❌ 删除配置", callback_data=f"ads:item:delete:{chat_id}:{item.id}"),
            InlineKeyboardButton("🔙 返回", callback_data=f"ads:list:{chat_id}:0"),
        ],
    ])


def ads_item_time_keyboard(chat_id: int, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("开始时间", callback_data=f"ads:item:input:{chat_id}:{item_id}:start"),
            InlineKeyboardButton("结束时间", callback_data=f"ads:item:input:{chat_id}:{item_id}:end"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"ads:detail:{chat_id}:{item_id}")],
    ])


def ads_rules_interval_keyboard(chat_id: int, current_interval_seconds: int | None) -> InlineKeyboardMarkup:
    current_minutes = max(int(current_interval_seconds or 7200) // 60, 1)
    options = [
        [1, 3, 5, 10],
        [15, 20, 30, 45],
        [60, 120, 180, 240],
        [360, 480, 720, 1440],
    ]
    return build_interval_keyboard(
        current_minutes=current_minutes,
        option_rows=options,
        callback_factory=lambda value: f"ads:rules:set:{chat_id}:interval_minutes:{value}",
        back_callback=f"ads:rules:{chat_id}",
        custom_callback=f"ads:rules:input:{chat_id}:interval_custom",
    )


def ads_copy_time_keyboard(back_callback: str, sample_time: str) -> InlineKeyboardMarkup:
    return build_back_keyboard(back_callback)


def describe_manage_delete_policy(rule) -> str:
    return describe_delete_policy(rule)
