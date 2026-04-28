from __future__ import annotations

import datetime as dt

import structlog
from telegram.ext import ContextTypes

from backend.features.group_ops.group_hooks.common import _schedule_message_delete
from backend.features.moderation.services.user_action_runtime import execute_user_action

log = structlog.get_logger(__name__)


def _is_night_time(settings) -> bool:
    if not bool(getattr(settings, "night_mode_enabled", False)):
        return False
    start_time = getattr(settings, "night_mode_start_time", None)
    end_time = getattr(settings, "night_mode_end_time", None)
    if not start_time or not end_time:
        return False
    try:
        start_hour, start_minute = [int(x) for x in start_time.split(":", 1)]
        end_hour, end_minute = [int(x) for x in end_time.split(":", 1)]
    except Exception:
        return False
    now = dt.datetime.now().time()
    now_min = now.hour * 60 + now.minute
    start_min = start_hour * 60 + start_minute
    end_min = end_hour * 60 + end_minute
    if start_min == end_min:
        return False
    if end_min < start_min:
        return now_min >= start_min or now_min < end_min
    return start_min <= now_min < end_min


async def _process_night_mode(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    message,
    settings,
    is_admin: bool,
    night_time_check=_is_night_time,
) -> bool:
    if not night_time_check(settings):
        return False
    if is_admin and bool(getattr(settings, "night_mode_exempt_admin", True)):
        return False
    whitelist = getattr(settings, "night_mode_whitelist_user_ids", None) or []
    if user.id in set(int(item) for item in whitelist if isinstance(item, (int, str))):
        return False

    if bool(getattr(settings, "night_mode_delete_message", True)):
        await execute_user_action(
            context,
            feature="夜间管控",
            chat_id=chat.id,
            user_id=user.id,
            action="none",
            detail="夜间管控命中，删除发言",
            message=message,
            delete_message=True,
        )

    if bool(getattr(settings, "night_mode_warn_enabled", True)):
        warn_text = getattr(settings, "night_mode_warn_text", None) or "🌙 夜间管控生效中，请稍后再试。"
        try:
            sent = await context.bot.send_message(
                chat.id,
                warn_text,
                reply_to_message_id=getattr(message, "message_id", None),
            )
            delete_after = int(getattr(settings, "night_mode_warn_delete_after_seconds", 60) or 60)
            if delete_after > 0:
                _schedule_message_delete(context, sent, delete_after, name="group_hooks.night_mode_warn_delete")
        except Exception as exc:
            log.warning("night_mode_warn_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    return True
