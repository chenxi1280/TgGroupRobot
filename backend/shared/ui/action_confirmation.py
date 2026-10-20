"""One-use, user-scoped confirmations for existing administrative actions."""
import hashlib
import json
import secrets
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from backend.shared.handlers.base.message_helper import MessageHelper

TTL_SECONDS = 600


async def confirm_action(update, context, *, callback: str, back: str, text: str, version=None) -> bool:
    """Call only after authorization and object lookup; True permits the action.

    This is an interaction guard, not a replacement for durable delivery
    idempotency or domain transaction locks. Restart invalidates pending dialogs.
    """
    pending = context.user_data.setdefault("ui_confirmations", {})
    now = time.time()
    for key in list(pending):
        if pending[key]["expires"] <= now:
            pending.pop(key)
    digest = hashlib.sha256(json.dumps(version, sort_keys=True, default=str).encode()).hexdigest()
    data = update.callback_query.data or ""
    if data != callback:
        saved = pending.get(callback)
        expected = f"{callback}:ok:{saved['token']}" if saved else None
        if data != expected or saved["version"] != digest:
            await MessageHelper.safe_answer(update, "确认已过期或内容已变化，请重新打开；本次未执行", show_alert=True)
            return False
        pending.pop(callback)
        return True
    token = secrets.token_hex(4)
    pending[callback] = {"token": token, "expires": now + TTL_SECONDS, "version": digest}
    await MessageHelper.safe_edit(update, text, reply_markup=InlineKeyboardMarkup([[
        InlineKeyboardButton("取消", callback_data=back),
        InlineKeyboardButton("确认执行", callback_data=f"{callback}:ok:{token}"),
    ]]))
    return False
