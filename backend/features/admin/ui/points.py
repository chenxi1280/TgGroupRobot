"""积分配置键盘"""
from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def _toggle_labels(enabled: bool, on_text: str = "启动", off_text: str = "关闭") -> tuple[str, str]:
    return (f"✅ {on_text}", off_text) if enabled else (on_text, f"✅ {off_text}")


def points_config_keyboard(settings, chat_id: int) -> InlineKeyboardMarkup:
    """主积分首页键盘"""
    all_enabled = bool(settings.sign_enabled or settings.message_points_enabled or settings.invite_points_enabled)
    state_on, state_off = _toggle_labels(all_enabled)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ 状态：", callback_data=f"pts:home:{chat_id}"),
            InlineKeyboardButton(state_on, callback_data=f"pts:toggle:all_enabled:{chat_id}:1"),
            InlineKeyboardButton(state_off, callback_data=f"pts:toggle:all_enabled:{chat_id}:0"),
        ],
        [
            InlineKeyboardButton("📘 展示规则：", callback_data=f"pts:view:display_rules:{chat_id}"),
            InlineKeyboardButton("查看", callback_data=f"pts:view:display_rules:{chat_id}"),
        ],
        [
            InlineKeyboardButton("🏆 发言总排行", callback_data=f"pts:view:speech_rank:{chat_id}"),
            InlineKeyboardButton("查看", callback_data=f"pts:view:speech_rank:{chat_id}"),
        ],
        [
            InlineKeyboardButton("👤 个人发言量", callback_data=f"pts:view:personal_speech:{chat_id}"),
            InlineKeyboardButton("查看", callback_data=f"pts:view:personal_speech:{chat_id}"),
        ],
        [
            InlineKeyboardButton("📅 签到规则", callback_data=f"pts:rule:checkin:{chat_id}"),
            InlineKeyboardButton("💬 发言规则", callback_data=f"pts:rule:speech:{chat_id}"),
            InlineKeyboardButton("🔗 邀请规则", callback_data=f"pts:rule:invite:{chat_id}"),
        ],
        [
            InlineKeyboardButton("🧾 积分任务", callback_data=f"pts:view:tasks:{chat_id}"),
            InlineKeyboardButton("🧩 额外规则", callback_data=f"pts:view:extra_rules:{chat_id}"),
        ],
        [
            InlineKeyboardButton("🔄 转让积分", callback_data=f"pts:edit:transfer:{chat_id}"),
            InlineKeyboardButton("🏷️ 积分别名", callback_data=f"pts:edit:points_alias:{chat_id}"),
            InlineKeyboardButton("🥇 排行别名", callback_data=f"pts:edit:points_rank_alias:{chat_id}"),
        ],
        [
            InlineKeyboardButton("➕ 增加积分", callback_data=f"pts:edit:admin_add:{chat_id}"),
            InlineKeyboardButton("➖ 扣除积分", callback_data=f"pts:edit:admin_deduct:{chat_id}"),
        ],
        [
            InlineKeyboardButton("🎁 积分抽奖", callback_data=f"adm:menu:lottery:{chat_id}"),
        ],
        [
            InlineKeyboardButton("📤 导出操作日志", callback_data=f"pts:view:export_logs:{chat_id}"),
            InlineKeyboardButton("🧹 清空积分", callback_data=f"pts:edit:clear_points:{chat_id}"),
        ],
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ])


def points_rule_keyboard(rule_type: str, settings, chat_id: int) -> InlineKeyboardMarkup:
    """签到/发言/邀请规则页键盘。"""
    if rule_type == "checkin":
        on_label, off_label = _toggle_labels(settings.sign_enabled)
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"pts:rule:checkin:{chat_id}"),
                InlineKeyboardButton(on_label, callback_data=f"pts:toggle:sign_enabled:{chat_id}:1"),
                InlineKeyboardButton(off_label, callback_data=f"pts:toggle:sign_enabled:{chat_id}:0"),
            ],
            [InlineKeyboardButton("🎯 设置获得数量", callback_data=f"pts:edit:sign_points:{chat_id}")],
            [InlineKeyboardButton("🔥 连续奖励", callback_data=f"pts:edit:sign_consecutive:{chat_id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"pts:home:{chat_id}")],
        ])
    if rule_type == "speech":
        on_label, off_label = _toggle_labels(settings.message_points_enabled)
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("⚙️ 状态：", callback_data=f"pts:rule:speech:{chat_id}"),
                InlineKeyboardButton(on_label, callback_data=f"pts:toggle:message_points_enabled:{chat_id}:1"),
                InlineKeyboardButton(off_label, callback_data=f"pts:toggle:message_points_enabled:{chat_id}:0"),
            ],
            [InlineKeyboardButton("🎯 设置获得数量", callback_data=f"pts:edit:message_points:{chat_id}")],
            [InlineKeyboardButton("📈 每日上限", callback_data=f"pts:edit:message_daily_limit:{chat_id}")],
            [InlineKeyboardButton("🔡 最小字数长度限制", callback_data=f"pts:edit:message_min_length:{chat_id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"pts:home:{chat_id}")],
        ])
    on_label, off_label = _toggle_labels(settings.invite_points_enabled)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚙️ 状态：", callback_data=f"pts:rule:invite:{chat_id}"),
            InlineKeyboardButton(on_label, callback_data=f"pts:toggle:invite_points_enabled:{chat_id}:1"),
            InlineKeyboardButton(off_label, callback_data=f"pts:toggle:invite_points_enabled:{chat_id}:0"),
        ],
        [InlineKeyboardButton("🎯 设置获得数量", callback_data=f"pts:edit:invite_points:{chat_id}")],
        [InlineKeyboardButton("📈 设置每日上限", callback_data=f"pts:edit:invite_daily_limit:{chat_id}")],
        [InlineKeyboardButton("🔙 返回", callback_data=f"pts:home:{chat_id}")],
    ])


def back_button(chat_id: int, callback_data: str | None = None) -> InlineKeyboardMarkup:
    """返回按钮"""
    target = callback_data or f"pts:home:{chat_id}"
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=target)]])
