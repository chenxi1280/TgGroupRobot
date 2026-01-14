from __future__ import annotations

import structlog
from telegram import ChatMember
from telegram.ext import ContextTypes
from telegram.error import TelegramError

log = structlog.get_logger(__name__)


async def is_user_admin(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    """检查用户是否是群组管理员"""
    try:
        m: ChatMember = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        is_admin = m.status in ("administrator", "creator")
        log.info("check_admin_status", chat_id=chat_id, user_id=user_id, status=m.status, is_admin=is_admin)
        return is_admin
    except TelegramError as e:
        log.warning("failed_to_check_admin_status", chat_id=chat_id, user_id=user_id, error=str(e))
        return False





