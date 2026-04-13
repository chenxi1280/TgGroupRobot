from __future__ import annotations

from backend.features.subscription.renewal_handler import handle_renewal_card_input as subscription_card_message_handler


async def subscription_menu_callback(update, context):
    if update.callback_query is None:
        return
    await renew_callback_alias(update, context)


async def renew_callback_alias(update, context):
    from backend.features.subscription.renewal_handler import renew_callback

    data = update.callback_query.data or ""
    if data.startswith("sub:menu:"):
        update.callback_query.data = data.replace("sub:menu:", "renew:menu:", 1)
    elif data.startswith("sub:contact:"):
        update.callback_query.data = data.replace("sub:contact:", "renew:contact:", 1)
    await renew_callback(update, context)


async def subscription_contact_callback(update, context):
    await renew_callback_alias(update, context)


__all__ = [
    "subscription_menu_callback",
    "subscription_contact_callback",
    "subscription_card_message_handler",
]
