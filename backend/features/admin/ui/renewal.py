from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def renewal_entry_keyboard(
    chat_id: int,
    *,
    contact_username: str | None = None,
    contact_url: str | None = None,
    contact_label: str = "一键联系",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔙 返回", callback_data=f"renew:back:{chat_id}")],
        ]
    )
