from __future__ import annotations

from telegram import ChatMember
from telegram.ext import ContextTypes


async def is_user_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    m: ChatMember = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
    return m.status in ("administrator", "creator")





