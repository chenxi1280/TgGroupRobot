from __future__ import annotations

import datetime as dt

import structlog
from telegram.ext import ContextTypes

from backend.shared.services.action_executor import ActionExecutor
from backend.shared.services.publish_service import PublishService

log = structlog.get_logger(__name__)


def _garage_limit_hits_message(message, message_text: str, mode: str) -> bool:
    has_media = any(
        getattr(message, attr, None)
        for attr in ("photo", "video", "document", "animation")
    )
    if mode == "image":
        return bool(has_media)
    if mode == "image_text":
        return bool(has_media or message_text.strip())
    return False


async def _process_garage_limit(
    context: ContextTypes.DEFAULT_TYPE,
    session,
    chat,
    user,
    message,
    message_text: str,
    settings,
    *,
    is_admin: bool,
    is_teacher: bool,
    is_whitelisted: bool,
) -> bool:
    if not getattr(settings, "garage_limit_enabled", False) or is_admin or not is_teacher or is_whitelisted:
        return False

    mode = getattr(settings, "garage_limit_mode", "none")
    if not _garage_limit_hits_message(message, message_text, mode):
        return False

    tracker = context.application.bot_data.setdefault("garage_limit_tracker", {})
    key = (chat.id, user.id)
    now_ts = dt.datetime.now(dt.UTC).timestamp()
    interval = max(int(getattr(settings, "garage_limit_interval_sec", 3600) or 3600), 1)
    max_count = max(int(getattr(settings, "garage_limit_max_count", 1) or 1), 1)
    history = [ts for ts in tracker.get(key, []) if now_ts - ts < interval]
    history.append(now_ts)
    tracker[key] = history
    if len(history) <= max_count:
        return False

    await session.commit()
    try:
        await ActionExecutor.execute(
            context,
            action="delete",
            chat_id=chat.id,
            user_id=user.id,
            reason="车库发言限制",
            actor_user_id=None,
            message_id=message.message_id,
            sender_chat_id=getattr(getattr(message, "sender_chat", None), "id", None),
        )
    except Exception as exc:
        log.warning("garage_limit_delete_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    await PublishService.send_temporary(
        context,
        chat_id=chat.id,
        text="当前老师发言过于频繁，消息已被限制。",
        delete_after_seconds=15,
    )
    return True
