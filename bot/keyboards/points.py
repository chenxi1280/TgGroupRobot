from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def points_config_keyboard(settings, chat_id: int) -> InlineKeyboardMarkup:
    """积分配置键盘"""
    # 签到状态
    sign_status = "✅ 开启" if settings.sign_enabled else "❌ 关闭"
    sign_consecutive = f"{settings.sign_consecutive_days}天+{settings.sign_consecutive_bonus}分" if settings.sign_consecutive_days > 0 else "未设置"

    # 发言积分状态
    msg_status = "✅ 开启" if settings.message_points_enabled else "❌ 关闭"
    msg_daily = f"{settings.message_points_daily_limit}" if settings.message_points_daily_limit else "无限制"
    msg_min_len = f"{settings.message_min_length}字" if settings.message_min_length else "无限制"

    # 邀请积分状态
    inv_status = "✅ 开启" if settings.invite_points_enabled else "❌ 关闭"
    inv_daily = f"{settings.invite_points_daily_limit}" if settings.invite_points_daily_limit else "无限制"

    buttons = [
        # 签到规则
        [InlineKeyboardButton(f"签到: {sign_status}", callback_data=f"pts:toggle:sign_enabled:{chat_id}")],
        [InlineKeyboardButton(f"签到积分: {settings.sign_points}", callback_data=f"pts:edit:sign_points:{chat_id}")],
        [InlineKeyboardButton(f"连续奖励: {sign_consecutive}", callback_data=f"pts:edit:sign_consecutive:{chat_id}")],
        # 分隔
        [InlineKeyboardButton("━" * 15, callback_data="pts:separator")],
        # 发言规则
        [InlineKeyboardButton(f"发言积分: {msg_status}", callback_data=f"pts:toggle:message_points_enabled:{chat_id}")],
        [InlineKeyboardButton(f"每次积分: {settings.message_points}", callback_data=f"pts:edit:message_points:{chat_id}")],
        [InlineKeyboardButton(f"每日上限: {msg_daily}", callback_data=f"pts:edit:message_daily_limit:{chat_id}")],
        [InlineKeyboardButton(f"最小字数: {msg_min_len}", callback_data=f"pts:edit:message_min_length:{chat_id}")],
        # 分隔
        [InlineKeyboardButton("━" * 15, callback_data="pts:separator")],
        # 邀请规则
        [InlineKeyboardButton(f"邀请积分: {inv_status}", callback_data=f"pts:toggle:invite_points_enabled:{chat_id}")],
        [InlineKeyboardButton(f"每次积分: {settings.invite_points}", callback_data=f"pts:edit:invite_points:{chat_id}")],
        [InlineKeyboardButton(f"每日上限: {inv_daily}", callback_data=f"pts:edit:invite_daily_limit:{chat_id}")],
        # 分隔
        [InlineKeyboardButton("━" * 15, callback_data="pts:separator")],
        # 别名设置
        [InlineKeyboardButton(f"积分别名: {settings.points_alias}", callback_data=f"pts:edit:points_alias:{chat_id}")],
        [InlineKeyboardButton(f"排行别名: {settings.points_rank_alias}", callback_data=f"pts:edit:points_rank_alias:{chat_id}")],
        # 返回
        [InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")],
    ]
    return InlineKeyboardMarkup(buttons)


def back_button(chat_id: int) -> InlineKeyboardMarkup:
    """返回按钮"""
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")]])
