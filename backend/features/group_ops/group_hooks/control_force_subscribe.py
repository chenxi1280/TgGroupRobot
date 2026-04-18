from __future__ import annotations

import datetime as dt
import html
from urllib.parse import urlparse

import structlog
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.group_ops.group_hooks.common import _schedule_message_delete

log = structlog.get_logger(__name__)


def _normalize_force_subscribe_target(value: str | int | None) -> str | int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    if (raw.startswith("-") and raw[1:].isdigit()) or raw.isdigit():
        return int(raw)
    if raw.startswith("@") and len(raw) > 1 and "/" not in raw and "?" not in raw:
        return raw

    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {"t.me", "www.t.me"}:
        return None
    if parsed.query or parsed.fragment:
        return None
    path = parsed.path.strip("/")
    if not path or "/" in path or path.startswith("+") or path == "joinchat":
        return None
    return f"@{path}"


def _force_subscribe_target_fallback_label(value: str | int | None) -> str:
    if value is None:
        return "关注频道/群组"
    raw = str(value).strip()
    if not raw:
        return "关注频道/群组"
    if raw.startswith("@"):
        return raw
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {"t.me", "www.t.me"}:
        path = parsed.path.strip("/")
        if path and "/" not in path and not path.startswith("+") and path != "joinchat":
            return f"@{path}"
    return raw


def _force_subscribe_target_url(value: str | int | None, target_chat=None) -> str | None:
    username = str(getattr(target_chat, "username", "") or "").strip()
    if username:
        return f"https://t.me/{username.lstrip('@')}"
    if not value:
        return None
    raw = str(value).strip()
    if raw.startswith("@"):
        return f"https://t.me/{raw[1:]}"
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {"t.me", "www.t.me"}:
        if not parsed.query and not parsed.fragment:
            return raw
    return None


def _force_subscribe_label_from_chat(target_chat, fallback: str) -> str:
    for attr in ("title", "full_name"):
        value = str(getattr(target_chat, attr, "") or "").strip()
        if value:
            return value
    username = str(getattr(target_chat, "username", "") or "").strip()
    if username:
        return f"@{username.lstrip('@')}"
    return fallback


async def _resolve_force_subscribe_target_chat(context: ContextTypes.DEFAULT_TYPE, value: str | int | None):
    target = _normalize_force_subscribe_target(value)
    if target is None:
        return None
    bot = getattr(context, "bot", None)
    if bot is None or not hasattr(bot, "get_chat"):
        return None
    try:
        return await bot.get_chat(chat_id=target)
    except Exception as exc:
        log.debug(
            "force_subscribe_target_title_resolve_failed",
            target=value,
            normalized_target=target,
            error=str(exc),
        )
        return None


async def _resolve_force_subscribe_target_label(context: ContextTypes.DEFAULT_TYPE, value: str | int | None) -> str:
    fallback = _force_subscribe_target_fallback_label(value)
    target_chat = await _resolve_force_subscribe_target_chat(context, value)
    if target_chat is None:
        return fallback
    return _force_subscribe_label_from_chat(target_chat, fallback)


def _build_force_subscribe_channel_button(
    value: str | int | None,
    *,
    label: str | None = None,
    target_chat=None,
) -> InlineKeyboardButton | None:
    if not value:
        return None
    text = (label or _force_subscribe_target_fallback_label(value)).strip()
    url = _force_subscribe_target_url(value, target_chat=target_chat)
    if url is None:
        return None
    return InlineKeyboardButton(text[:64], url=url)


async def _build_resolved_force_subscribe_channel_button(
    context: ContextTypes.DEFAULT_TYPE,
    value: str | int | None,
) -> InlineKeyboardButton | None:
    if not value:
        return None
    fallback = _force_subscribe_target_fallback_label(value)
    target_chat = await _resolve_force_subscribe_target_chat(context, value)
    label = _force_subscribe_label_from_chat(target_chat, fallback) if target_chat is not None else fallback
    return _build_force_subscribe_channel_button(value, label=label, target_chat=target_chat)


def _is_force_subscribe_member(member) -> bool:
    status = getattr(member, "status", None)
    if status in {"left", "kicked"}:
        return False
    if status == "restricted" and hasattr(member, "is_member"):
        return bool(getattr(member, "is_member"))
    return True


async def _build_force_subscribe_markup(context: ContextTypes.DEFAULT_TYPE, settings) -> InlineKeyboardMarkup | None:
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

    buttons: list[InlineKeyboardButton] = []
    for value in (
        getattr(settings, "force_subscribe_bound_channel_1", None),
        getattr(settings, "force_subscribe_bound_channel_2", None),
    ):
        button = await _build_resolved_force_subscribe_channel_button(context, value)
        if button is not None:
            buttons.append(button)
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

    configured_targets = [
        getattr(settings, "force_subscribe_bound_channel_1", None),
        getattr(settings, "force_subscribe_bound_channel_2", None),
    ]
    configured_targets = [target for target in configured_targets if target]
    if not configured_targets:
        return True

    subscribed_results: list[bool] = []
    for configured_target in configured_targets:
        target = _normalize_force_subscribe_target(configured_target)
        if target is None:
            subscribed_results.append(False)
            log.warning(
                "force_subscribe_target_invalid",
                chat_id=chat.id,
                user_id=user.id,
                target=configured_target,
            )
            continue
        try:
            member = await context.bot.get_chat_member(chat_id=target, user_id=user.id)
            subscribed_results.append(_is_force_subscribe_member(member))
        except Exception as exc:
            subscribed_results.append(False)
            log.warning(
                "force_subscribe_check_failed",
                chat_id=chat.id,
                user_id=user.id,
                target=configured_target,
                normalized_target=target,
                error=str(exc),
            )

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
        guide_text = getattr(settings, "force_subscribe_guide_text", None) or "{member}，您需要关注指定频道/群组后才能发言。"
        text = (
            guide_text
            .replace("{member}", html.escape(user.full_name))
            .replace("{userid}", str(user.id))
            .replace("{nickname}", html.escape(user.full_name))
        )
        markup = await _build_force_subscribe_markup(context, settings)
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
                _schedule_message_delete(context, sent, delete_after, name="group_hooks.force_subscribe_warn_delete")
        except Exception as exc:
            log.warning("force_subscribe_warn_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    return False
