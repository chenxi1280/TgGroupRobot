from __future__ import annotations

import structlog
from telegram import ChatMember
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from bot.config import get_settings

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


def get_bot_admin_ids(context: ContextTypes.DEFAULT_TYPE | None = None) -> set[int]:
    """获取 Bot 全局管理员 ID 集合（来自 BOT_ADMIN_IDS）"""
    settings = context.application.bot_data.get("settings") if context is not None else get_settings()
    raw = (settings.bot_admin_ids or "").strip()
    if not raw:
        return set()

    ids: set[int] = set()
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError:
            log.warning("invalid_bot_admin_id", value=item)
    return ids


def is_bot_admin_user(user_id: int, context: ContextTypes.DEFAULT_TYPE | None = None) -> bool:
    """检查用户是否为 Bot 全局管理员"""
    return user_id in get_bot_admin_ids(context)




