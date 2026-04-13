from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def subscription_menu_keyboard(
    chat_id: int,
    *,
    contact_url: str | None,
    contact_label: str = "一键联系",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    if contact_url:
        rows.append([InlineKeyboardButton(contact_label, url=contact_url)])
    else:
        rows.append([InlineKeyboardButton(contact_label, callback_data=f"sub:contact:{chat_id}")])

    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"adm:menu:main:{chat_id}")])
    return InlineKeyboardMarkup(rows)
