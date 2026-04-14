from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def verification_mode_menu(current_mode: str, chat_id: int | None = None) -> InlineKeyboardMarkup:
    if chat_id is not None:
        back_callback = f"adm:menu:main:{chat_id}"
        callbacks = [
            f"adm:vfy_mode:{chat_id}:button",
            f"adm:vfy_mode:{chat_id}:math",
            f"adm:vfy_mode:{chat_id}:captcha",
            f"adm:vfy_mode:{chat_id}:admin",
        ]
    else:
        back_callback = "adm:menu:verification"
        callbacks = ["adm:vfy_mode:button", "adm:vfy_mode:math", "adm:vfy_mode:captcha", "adm:vfy_mode:admin"]

    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔘 按钮验证", callback_data=callbacks[0])],
            [InlineKeyboardButton("🔢 数学题验证", callback_data=callbacks[1])],
            [InlineKeyboardButton("🔑 验证码验证", callback_data=callbacks[2])],
            [InlineKeyboardButton("👤 管理员确认", callback_data=callbacks[3])],
            [InlineKeyboardButton("🔙 返回", callback_data=back_callback)],
        ]
    )


def verification_config_menu(
    enabled: bool,
    mode: str,
    timeout_seconds: int,
    timeout_action: str,
    restrict_can_send: bool,
    chat_id: int | None = None,
) -> InlineKeyboardMarkup:
    status_prefix = "✅" if enabled else "❌"
    mode_label = {"button": "按钮验证", "math": "数学题", "captcha": "验证码", "admin": "管理员"}.get(mode, mode)
    action_label = {"mute": "禁言", "kick": "踢出"}.get(timeout_action, timeout_action)
    restrict_prefix = "✅" if restrict_can_send else "❌"

    if chat_id is not None:
        back_callback = f"adm:menu:main:{chat_id}"
        buttons = [
            [InlineKeyboardButton(f"{status_prefix} 验证开关", callback_data=f"adm:vfy_toggle:{chat_id}")],
            [InlineKeyboardButton(f"🔘 验证方式: {mode_label}", callback_data=f"adm:vfy_mode_menu:{chat_id}")],
            [InlineKeyboardButton(f"⏱️ 超时时间: {timeout_seconds}秒", callback_data=f"adm:vfy_timeout:{chat_id}")],
            [InlineKeyboardButton(f"🔇 超时处理: {action_label}", callback_data=f"adm:vfy_action:{chat_id}")],
            [InlineKeyboardButton(f"{restrict_prefix} 限制发言", callback_data=f"adm:vfy_restrict:{chat_id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=back_callback)],
        ]
    else:
        buttons = [
            [InlineKeyboardButton(f"{status_prefix} 验证开关", callback_data="adm:vfy_toggle")],
            [InlineKeyboardButton(f"🔘 验证方式: {mode_label}", callback_data="adm:vfy_mode_menu")],
            [InlineKeyboardButton(f"⏱️ 超时时间: {timeout_seconds}秒", callback_data="adm:vfy_timeout")],
            [InlineKeyboardButton(f"🔇 超时处理: {action_label}", callback_data="adm:vfy_action")],
            [InlineKeyboardButton(f"{restrict_prefix} 限制发言", callback_data="adm:vfy_restrict")],
            [InlineKeyboardButton("🔙 返回", callback_data="adm:menu:verification")],
        ]
    return InlineKeyboardMarkup(buttons)


def verification_timeout_action_menu(current_action: str, chat_id: int | None = None) -> InlineKeyboardMarkup:
    if chat_id is not None:
        back_callback = f"adm:vfy_config:{chat_id}"
        callbacks = [f"adm:vfy_action:{chat_id}:mute", f"adm:vfy_action:{chat_id}:kick"]
    else:
        back_callback = "adm:vfy_config"
        callbacks = ["adm:vfy_action:mute", "adm:vfy_action:kick"]
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔇 禁言", callback_data=callbacks[0])],
            [InlineKeyboardButton("👢 踢出群聊", callback_data=callbacks[1])],
            [InlineKeyboardButton("🔙 返回", callback_data=back_callback)],
        ]
    )
