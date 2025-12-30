from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def admin_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("群设置", callback_data="adm:menu:settings"),
                InlineKeyboardButton("积分", callback_data="adm:menu:points"),
            ],
            [
                InlineKeyboardButton("新人验证", callback_data="adm:menu:verification"),
                InlineKeyboardButton("内容审核", callback_data="adm:menu:moderation"),
            ],
            [
                InlineKeyboardButton("广告与订阅", callback_data="adm:menu:ads"),
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





