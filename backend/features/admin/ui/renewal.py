from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def renewal_entry_keyboard(
    chat_id: int,
    *,
    contact_username: str | None = None,
    contact_url: str | None = None,
    contact_label: str = "一键联系",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton("🔑 输入续费卡密", callback_data=f"renew:input:{chat_id}")],
    ]
    if contact_url:
        rows.append([InlineKeyboardButton(contact_label, url=contact_url)])
    elif contact_username:
        rows.append([InlineKeyboardButton(contact_label, url=f"https://t.me/{contact_username.lstrip('@')}")])
    rows.append([InlineKeyboardButton("🔙 返回", callback_data=f"renew:back:{chat_id}")])
    return InlineKeyboardMarkup(rows)
