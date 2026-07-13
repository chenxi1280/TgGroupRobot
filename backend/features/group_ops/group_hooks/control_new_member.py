from __future__ import annotations

import datetime as dt
import html

import structlog
from sqlalchemy import select
from telegram.ext import ContextTypes

from backend.features.group_ops.group_hooks.common import _schedule_message_delete
from backend.features.moderation.services.user_action_runtime import execute_user_action
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ChatMember
from backend.shared.services.formatters import format_user_display_name

log = structlog.get_logger(__name__)

DEFAULT_LIMIT_WINDOW_SECONDS = 3600
DEFAULT_WARN_DELETE_SECONDS = 60
MEDIA_ATTRIBUTES = (
    "photo",
    "video",
    "document",
    "animation",
    "sticker",
    "audio",
    "voice",
    "video_note",
)


def _message_contains_link(message) -> bool:
    entities = list(getattr(message, "entities", None) or [])
    entities.extend(getattr(message, "caption_entities", None) or [])
    for entity in entities:
        if getattr(entity, "type", None) in {"url", "text_link"}:
            return True
    text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").lower()
    return "http://" in text or "https://" in text or "t.me/" in text


def _format_duration_label(seconds: int) -> str:
    safe_seconds = max(int(seconds or 0), 0)
    if safe_seconds <= 0:
        return "0分钟"
    minutes = (safe_seconds + 59) // 60
    hours, rem = divmod(minutes, 60)
    if hours:
        if rem:
            return f"{hours}小时{rem}分钟"
        return f"{hours}小时"
    return f"{minutes}分钟"


async def _get_member_joined_at(db: Database, chat_id: int, user_id: int) -> dt.datetime | None:
    async with db.session_factory() as session:
        result = await session.execute(
            select(ChatMember.joined_at).where(
                ChatMember.chat_id == chat_id,
                ChatMember.user_id == user_id,
            )
        )
        await session.commit()
    return result.scalar_one_or_none()


def _is_blocked_message(message, settings) -> bool:
    message_text = getattr(message, "text", None) or getattr(message, "caption", None) or ""
    has_media = any(getattr(message, attribute, None) for attribute in MEDIA_ATTRIBUTES)
    has_link = _message_contains_link(message)
    blocks_media = bool(getattr(settings, "new_member_limit_block_media", True)) and has_media
    blocks_link = bool(getattr(settings, "new_member_limit_block_links", True)) and has_link
    violates_text_only = bool(getattr(settings, "new_member_limit_text_only", False)) and (
        has_media or not message_text.strip()
    )
    return blocks_media or blocks_link or violates_text_only


def _build_warning_text(settings, user, remaining_seconds: int) -> str:
    template = (
        getattr(settings, "new_member_limit_warn_text", None)
        or "新成员需等待 {duration} 才可发送媒体/链接。"
    )
    duration_label = _format_duration_label(remaining_seconds)
    user_label = html.escape(format_user_display_name(user, user.id))
    return (
        template.replace("{duration}", duration_label)
        .replace("{member}", user_label)
        .replace("{userid}", str(user.id))
        .replace("{nickname}", user_label)
    )


async def _delete_blocked_message(context, chat, *, user, message, settings) -> None:
    if not bool(getattr(settings, "new_member_limit_delete_message", True)):
        return
    await execute_user_action(
        context,
        feature="新人限制",
        chat_id=chat.id,
        user_id=user.id,
        action="none",
        detail="新成员限制命中，删除违规发言",
        message=message,
        delete_message=True,
    )


async def _send_limit_warning(
    context,
    chat,
    *,
    user,
    message,
    settings,
    remaining_seconds: int,
) -> None:
    if not bool(getattr(settings, "new_member_limit_warn_enabled", True)):
        return
    text = _build_warning_text(settings, user, remaining_seconds)
    try:
        sent = await context.bot.send_message(
            chat.id,
            text,
            reply_to_message_id=getattr(message, "message_id", None),
            parse_mode="HTML",
        )
        delete_after = int(
            getattr(settings, "new_member_limit_warn_delete_after_seconds", DEFAULT_WARN_DELETE_SECONDS)
            or DEFAULT_WARN_DELETE_SECONDS
        )
        if delete_after > 0:
            _schedule_message_delete(context, sent, delete_after, name="group_hooks.new_member_warn_delete")
    except Exception as exc:
        log.warning("new_member_limit_warn_failed", chat_id=chat.id, user_id=user.id, error=str(exc))


async def _process_new_member_limit(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    *, user,
    message,
    settings,
    joined_at_lookup=_get_member_joined_at,
) -> bool:
    if not bool(getattr(settings, "new_member_limit_enabled", False)):
        return False

    joined_at = await joined_at_lookup(db, chat.id, user.id)
    if joined_at is None:
        return False

    window_seconds = int(
        getattr(settings, "new_member_limit_window_seconds", DEFAULT_LIMIT_WINDOW_SECONDS)
        or DEFAULT_LIMIT_WINDOW_SECONDS
    )
    if window_seconds <= 0:
        return False

    elapsed = (dt.datetime.now(dt.UTC) - joined_at).total_seconds()
    if elapsed >= window_seconds:
        return False

    if not _is_blocked_message(message, settings):
        return False

    remaining_seconds = max(0, int(window_seconds - elapsed))
    await _delete_blocked_message(context, chat, user=user, message=message, settings=settings)
    await _send_limit_warning(
        context,
        chat,
        user=user,
        message=message,
        settings=settings,
        remaining_seconds=remaining_seconds,
    )

    return True
