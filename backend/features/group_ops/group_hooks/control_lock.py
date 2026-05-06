from __future__ import annotations

import datetime as dt

import structlog
from telegram import ChatPermissions
from telegram.ext import ContextTypes

from backend.features.moderation.services.user_action_runtime import (
    delete_message_safely,
    execute_group_permission_action,
)

log = structlog.get_logger(__name__)


def _get_group_lock_schedule_times(settings) -> tuple[str | None, str | None]:
    night_start = getattr(settings, "night_mode_start_time", None)
    night_end = getattr(settings, "night_mode_end_time", None)
    if night_start and night_end:
        return night_end, night_start
    return (
        getattr(settings, "group_lock_open_time", None),
        getattr(settings, "group_lock_close_time", None),
    )


def _is_closed_by_schedule(settings) -> bool | None:
    if not bool(getattr(settings, "group_lock_schedule_enabled", False)):
        return None

    open_time, close_time = _get_group_lock_schedule_times(settings)
    if not open_time or not close_time:
        return False

    try:
        open_hour, open_minute = [int(x) for x in open_time.split(":", 1)]
        close_hour, close_minute = [int(x) for x in close_time.split(":", 1)]
    except Exception as exc:
        log.warning("group_lock_schedule_parse_failed", open_time=open_time, close_time=close_time, error=str(exc))
        return None

    now = dt.datetime.now().time()
    now_min = now.hour * 60 + now.minute
    open_min = open_hour * 60 + open_minute
    close_min = close_hour * 60 + close_minute
    if open_min == close_min:
        return None
    if close_min < open_min:
        return close_min <= now_min < open_min
    return now_min >= close_min or now_min < open_min


async def _apply_group_lock_permissions(context: ContextTypes.DEFAULT_TYPE, chat_id: int, closed: bool) -> None:
    permissions = ChatPermissions(can_send_messages=not closed)
    result = await execute_group_permission_action(
        context,
        chat_id=chat_id,
        permissions=permissions,
        feature="夜间管控",
        detail="按夜间管控配置调整群发言权限",
    )
    if result.failed:
        raise RuntimeError("; ".join(result.failures))


async def _process_group_lock_controls(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    message,
    settings,
    is_admin: bool,
    message_text: str,
) -> bool:
    lock_cache: dict[int, bool] = context.application.bot_data.setdefault("group_lock_state", {})
    desired_closed = _is_closed_by_schedule(settings)
    current_closed = lock_cache.get(chat.id)
    if desired_closed is not None and (current_closed is None or current_closed != desired_closed):
        try:
            await _apply_group_lock_permissions(context, chat.id, desired_closed)
            lock_cache[chat.id] = desired_closed
        except Exception as exc:
            log.warning("group_lock_schedule_apply_failed", chat_id=chat.id, error=str(exc))

    if not is_admin or not bool(getattr(settings, "group_lock_phrase_enabled", False)):
        return False

    try:
        member = await context.bot.get_chat_member(chat_id=chat.id, user_id=user.id)
    except Exception as exc:
        log.warning("group_lock_phrase_member_lookup_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
        return False

    if member.status != "creator" and not bool(getattr(member, "can_promote_members", False)):
        return False

    open_phrase = (getattr(settings, "group_lock_open_phrase", None) or "").strip()
    close_phrase = (getattr(settings, "group_lock_close_phrase", None) or "").strip()
    normalized = message_text.strip()
    if not normalized or normalized not in {open_phrase, close_phrase}:
        return False

    close_now = normalized == close_phrase
    applied = False
    try:
        await _apply_group_lock_permissions(context, chat.id, close_now)
        lock_cache[chat.id] = close_now
        applied = True
    except Exception as exc:
        log.warning("group_lock_phrase_apply_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    if applied and getattr(settings, "group_lock_delete_notice_mode", "keep") == "delete":
        await delete_message_safely(
            context,
            chat_id=chat.id,
            message=message,
            feature="夜间管控",
            detail="管理员口令触发群权限调整，删除口令消息",
        )
    return True
