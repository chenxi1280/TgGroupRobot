from __future__ import annotations

import datetime as dt
import html

import structlog
from sqlalchemy import select
from telegram.ext import ContextTypes

from backend.features.group_ops.group_hooks.common import _schedule_message_delete
from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ChatMember
from backend.shared.services.formatters import format_user_display_name

log = structlog.get_logger(__name__)


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


async def _process_new_member_limit(
    context: ContextTypes.DEFAULT_TYPE,
    db: Database,
    chat,
    user,
    message,
    settings,
    joined_at_lookup=_get_member_joined_at,
) -> bool:
    if not bool(getattr(settings, "new_member_limit_enabled", False)):
        return False

    joined_at = await joined_at_lookup(db, chat.id, user.id)
    if joined_at is None:
        return False

    window_seconds = int(getattr(settings, "new_member_limit_window_seconds", 3600) or 3600)
    if window_seconds <= 0:
        return False

    elapsed = (dt.datetime.now(dt.UTC) - joined_at).total_seconds()
    if elapsed >= window_seconds:
        return False

    message_text = (getattr(message, "text", None) or getattr(message, "caption", None) or "")
    has_media = any(
        getattr(message, attr, None)
        for attr in ("photo", "video", "document", "animation", "sticker", "audio", "voice", "video_note")
    )
    has_link = _message_contains_link(message)
    block_media = bool(getattr(settings, "new_member_limit_block_media", True))
    block_links = bool(getattr(settings, "new_member_limit_block_links", True))
    text_only = bool(getattr(settings, "new_member_limit_text_only", False))

    should_block = False
    if block_media and has_media:
        should_block = True
    if block_links and has_link:
        should_block = True
    if text_only and (has_media or not message_text.strip()):
        should_block = True

    if not should_block:
        return False

    if bool(getattr(settings, "new_member_limit_delete_message", True)):
        try:
            await message.delete()
        except Exception as exc:
            log.warning("new_member_limit_delete_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    if bool(getattr(settings, "new_member_limit_warn_enabled", True)):
        warn_text = getattr(settings, "new_member_limit_warn_text", None) or "新成员需等待 {duration} 才可发送媒体/链接。"
        remaining_seconds = max(0, int(window_seconds - elapsed))
        duration_label = _format_duration_label(remaining_seconds)
        user_label = html.escape(format_user_display_name(user, user.id))
        text = (
            warn_text
            .replace("{duration}", duration_label)
            .replace("{member}", user_label)
            .replace("{userid}", str(user.id))
            .replace("{nickname}", user_label)
        )
        try:
            sent = await context.bot.send_message(
                chat.id,
                text,
                reply_to_message_id=getattr(message, "message_id", None),
                parse_mode="HTML",
            )
            delete_after = int(getattr(settings, "new_member_limit_warn_delete_after_seconds", 60) or 60)
            if delete_after > 0:
                _schedule_message_delete(context, sent, delete_after, name="group_hooks.new_member_warn_delete")
        except Exception as exc:
            log.warning("new_member_limit_warn_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    return True
