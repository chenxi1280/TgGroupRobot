from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.features.subscription.services.subscription_renewal_service import build_contact_url


def renewal_entry_keyboard(
    chat_id: int,
    *,
    contact_username: str | None = None,
    contact_url: str | None = None,
    contact_label: str = "一键联系",
) -> InlineKeyboardMarkup:
    url = (contact_url or "").strip()
    if not url:
        url = build_contact_url(contact_username)

    contact_button = (
        InlineKeyboardButton(f"📞 {contact_label}", url=url)
        if url
        else InlineKeyboardButton("📞 未配置联系入口", callback_data=f"renew:contact:{chat_id}")
    )

    return InlineKeyboardMarkup(
        [
            [contact_button],
            [InlineKeyboardButton("🔑 输入卡密", callback_data=f"renew:input:{chat_id}")],
            [InlineKeyboardButton("🔙 返回", callback_data=f"renew:back:{chat_id}")],
        ]
    )
