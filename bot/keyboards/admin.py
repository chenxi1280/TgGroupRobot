from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def admin_main_menu() -> InlineKeyboardMarkup:
    """管理员主菜单（参考 WeGroupBot 样式）"""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🎁抽奖", callback_data="adm:menu:lottery"),
                InlineKeyboardButton("🔗邀请链接", callback_data="adm:menu:invite"),
            ],
            [
                InlineKeyboardButton("👋欢迎", callback_data="adm:menu:welcome"),
                InlineKeyboardButton("🤖验证", callback_data="adm:menu:verification"),
            ],
            [
                InlineKeyboardButton("💬自动回复", callback_data="adm:menu:autoreply"),
                InlineKeyboardButton("⏰定时消息", callback_data="adm:menu:scheduled"),
            ],
            [
                InlineKeyboardButton("🚫反垃圾", callback_data="adm:menu:antispam"),
                InlineKeyboardButton("🔇违禁词", callback_data="adm:menu:keywords"),
            ],
            [
                InlineKeyboardButton("💰积分", callback_data="adm:menu:points"),
                InlineKeyboardButton("📊统计", callback_data="adm:menu:stats"),
            ],
            [
                InlineKeyboardButton("⚙️群设置", callback_data="adm:menu:settings"),
            ],
        ]
    )


def back_button(to_menu: str = "main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data=f"adm:menu:{to_menu}")]])


def toggle_menu(rows: list[tuple[str, str, bool]], back_to: str) -> InlineKeyboardMarkup:
    kb: list[list[InlineKeyboardButton]] = []
    for label, key, enabled in rows:
        prefix = "✅" if enabled else "❌"
        kb.append([InlineKeyboardButton(f"{prefix} {label}", callback_data=f"adm:toggle:{key}")])
    kb.append([InlineKeyboardButton("返回", callback_data=f"adm:menu:{back_to}")])
    return InlineKeyboardMarkup(kb)


def verification_mode_menu(current_mode: str) -> InlineKeyboardMarkup:
    """验证模式选择菜单"""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔘 按钮验证", callback_data="adm:vfy_mode:button")],
            [InlineKeyboardButton("🔢 数学题验证", callback_data="adm:vfy_mode:math")],
            [InlineKeyboardButton("🔢 验证码验证", callback_data="adm:vfy_mode:captcha")],
            [InlineKeyboardButton("返回", callback_data="adm:menu:verification")],
        ]
    )





