from __future__ import annotations

import datetime as dt
import html

import structlog
from sqlalchemy import select
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.platform.db.runtime.session import Database
from backend.platform.db.schema.models.core import ChatMember
from backend.features.automation.services.scheduled_message_service import ScheduledMessageService

from .common import _delete_message_later

log = structlog.get_logger(__name__)


async def _process_rename_monitor(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    settings,
    old_username: str | None,
    old_name: str,
) -> bool:
    if not bool(getattr(settings, "name_change_monitor_enabled", False)):
        return False

    new_username = user.username or ""
    new_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    changes: list[tuple[str, str, str]] = []
    if (old_username or "") != new_username and (old_username or ""):
        changes.append(("用户名", old_username or "空", new_username or "空"))
    if old_name and old_name != new_name:
        changes.append(("昵称", old_name, new_name or "空"))
    if not changes:
        return False

    template = getattr(settings, "name_change_monitor_template_text", None) or (
        "检测到用户{userId}修改{changeType}\n原{changeType}: {oldContent}\n新{changeType}: {newContent}"
    )
    delete_after = int(getattr(settings, "name_change_monitor_delete_after_seconds", 60) or 60)

    for change_type, old_content, new_content in changes:
        text = (
            template
            .replace("{userId}", str(user.id))
            .replace("{changeType}", change_type)
            .replace("{oldContent}", old_content)
            .replace("{newContent}", new_content)
        )
        try:
            sent = await context.bot.send_message(chat.id, text)
            if delete_after > 0:
                import asyncio

                asyncio.create_task(_delete_message_later(sent, delete_after))
        except Exception as exc:
            log.warning("rename_monitor_send_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    return True


def _is_closed_by_schedule(settings) -> bool | None:
    if not bool(getattr(settings, "group_lock_schedule_enabled", False)):
        return None

    open_time = getattr(settings, "group_lock_open_time", None)
    close_time = getattr(settings, "group_lock_close_time", None)
    if not open_time or not close_time:
        return False

    try:
        open_hour, open_minute = [int(x) for x in open_time.split(":", 1)]
        close_hour, close_minute = [int(x) for x in close_time.split(":", 1)]
    except Exception:
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


async def _apply_group_lock_permissions(context: ContextTypes.DEFAULT_TYPE, chat_id: int, closed: bool) -> None:
    permissions = ChatPermissions(can_send_messages=not closed)
    await context.bot.set_chat_permissions(chat_id=chat_id, permissions=permissions)


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
    try:
        await _apply_group_lock_permissions(context, chat.id, close_now)
        lock_cache[chat.id] = close_now
        if getattr(settings, "group_lock_delete_notice_mode", "keep") == "delete":
            await message.delete()
    except Exception as exc:
        log.warning("group_lock_phrase_apply_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    return True


async def _process_night_mode(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    message,
    settings,
    is_admin: bool,
) -> bool:
    if not _is_night_time(settings):
        return False
    if is_admin and bool(getattr(settings, "night_mode_exempt_admin", True)):
        return False
    whitelist = getattr(settings, "night_mode_whitelist_user_ids", None) or []
    if user.id in set(int(item) for item in whitelist if isinstance(item, (int, str))):
        return False

    if bool(getattr(settings, "night_mode_delete_message", True)):
        try:
            await message.delete()
        except Exception as exc:
            log.warning("night_mode_delete_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    if bool(getattr(settings, "night_mode_warn_enabled", True)):
        warn_text = getattr(settings, "night_mode_warn_text", None) or "🌙 夜间模式生效中，请稍后再试。"
        try:
            sent = await context.bot.send_message(
                chat.id,
                warn_text,
                reply_to_message_id=getattr(message, "message_id", None),
            )
            delete_after = int(getattr(settings, "night_mode_warn_delete_after_seconds", 60) or 60)
            if delete_after > 0:
                import asyncio

                asyncio.create_task(_delete_message_later(sent, delete_after))
        except Exception as exc:
            log.warning("night_mode_warn_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    return True


def _build_force_subscribe_channel_button(value: str | None) -> InlineKeyboardButton | None:
    if not value:
        return None
    label = value
    url: str | None = None
    if value.startswith("@"):
        url = f"https://t.me/{value[1:]}"
    elif value.startswith("https://t.me/") or value.startswith("http://t.me/"):
        url = value
    if url is None:
        return None
    return InlineKeyboardButton(label, url=url)


def _build_force_subscribe_markup(settings) -> InlineKeyboardMarkup | None:
    custom_enabled = bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
    custom_buttons = getattr(settings, "force_subscribe_buttons", None) or []
    if custom_enabled and custom_buttons:
        try:
            normalized = ScheduledMessageService.normalize_buttons_config(custom_buttons)
            keyboard = [
                [InlineKeyboardButton(btn["text"], url=btn["url"]) for btn in row]
                for row in normalized
            ]
            if keyboard:
                return InlineKeyboardMarkup(keyboard)
        except Exception as exc:
            log.warning("force_subscribe_custom_buttons_invalid", error=str(exc))

    buttons = [
        button
        for button in (
            _build_force_subscribe_channel_button(getattr(settings, "force_subscribe_bound_channel_1", None)),
            _build_force_subscribe_channel_button(getattr(settings, "force_subscribe_bound_channel_2", None)),
        )
        if button is not None
    ]
    return InlineKeyboardMarkup([[button] for button in buttons]) if buttons else None


async def _check_force_subscribe(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    message,
    settings,
) -> bool:
    if not bool(getattr(settings, "force_subscribe_enabled", False)):
        return True

    channels = [
        getattr(settings, "force_subscribe_bound_channel_1", None),
        getattr(settings, "force_subscribe_bound_channel_2", None),
    ]
    channels = [channel for channel in channels if channel]
    if not channels:
        return True

    subscribed_results: list[bool] = []
    for channel in channels:
        try:
            member = await context.bot.get_chat_member(channel, user.id)
            subscribed_results.append(member.status not in {"left", "kicked"})
        except Exception:
            subscribed_results.append(False)

    check_mode = getattr(settings, "force_subscribe_check_mode", "all")
    subscribed = all(subscribed_results) if check_mode == "all" else any(subscribed_results)
    if subscribed:
        return True

    action = getattr(settings, "force_subscribe_not_subscribed_action", "delete_and_warn")
    if action in {"delete_and_warn", "delete_only"}:
        try:
            await message.delete()
        except Exception as exc:
            log.warning("force_subscribe_delete_failed", chat_id=chat.id, user_id=user.id, error=str(exc))
    if action == "mute":
        try:
            await context.bot.restrict_chat_member(
                chat.id,
                user.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=dt.datetime.now(dt.UTC) + dt.timedelta(minutes=10),
            )
        except Exception as exc:
            log.warning("force_subscribe_mute_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    if action in {"delete_and_warn", "warn_only", "mute"}:
        guide_text = getattr(settings, "force_subscribe_guide_text", None) or "{member}，您需要关注我们的频道才能发言。"
        text = (
            guide_text
            .replace("{member}", html.escape(user.full_name))
            .replace("{userid}", str(user.id))
            .replace("{nickname}", html.escape(user.full_name))
        )
        markup = _build_force_subscribe_markup(settings)
        try:
            cover_type = getattr(settings, "force_subscribe_cover_media_type", None)
            cover_file_id = getattr(settings, "force_subscribe_cover_file_id", None)
            if cover_type == "photo" and cover_file_id:
                sent = await context.bot.send_photo(
                    chat.id,
                    photo=cover_file_id,
                    caption=text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
            elif cover_type == "video" and cover_file_id:
                sent = await context.bot.send_video(
                    chat.id,
                    video=cover_file_id,
                    caption=text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
            else:
                sent = await context.bot.send_message(
                    chat.id,
                    text,
                    reply_markup=markup,
                    parse_mode="HTML",
                )
            delete_after = int(getattr(settings, "force_subscribe_delete_warn_after_seconds", 60) or 60)
            if delete_after > 0:
                import asyncio

                asyncio.create_task(_delete_message_later(sent, delete_after))
        except Exception as exc:
            log.warning("force_subscribe_warn_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    return False


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
) -> bool:
    if not bool(getattr(settings, "new_member_limit_enabled", False)):
        return False

    joined_at = await _get_member_joined_at(db, chat.id, user.id)
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
        text = (
            warn_text
            .replace("{duration}", duration_label)
            .replace("{member}", html.escape(user.full_name))
            .replace("{userid}", str(user.id))
            .replace("{nickname}", html.escape(user.full_name))
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
                import asyncio

                asyncio.create_task(_delete_message_later(sent, delete_after))
        except Exception as exc:
            log.warning("new_member_limit_warn_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    return True

