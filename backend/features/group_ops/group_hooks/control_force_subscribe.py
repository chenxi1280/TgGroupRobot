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


def _build_force_subscribe_channel_button(value: str | None) -> InlineKeyboardButton | None:
    if not value:
        return None
    label = value.strip()
    url: str | None = None
    if label.startswith("@"):
        url = f"https://t.me/{label[1:]}"
    elif label.startswith("https://t.me/") or label.startswith("http://t.me/"):
        parsed = urlparse(label)
        if not parsed.query and not parsed.fragment:
            url = label
    if url is None:
        return None
    return InlineKeyboardButton(label, url=url)


def _is_force_subscribe_member(member) -> bool:
    status = getattr(member, "status", None)
    if status in {"left", "kicked"}:
        return False
    if status == "restricted" and hasattr(member, "is_member"):
        return bool(getattr(member, "is_member"))
    return True


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
                _schedule_message_delete(context, sent, delete_after, name="group_hooks.force_subscribe_warn_delete")
        except Exception as exc:
            log.warning("force_subscribe_warn_failed", chat_id=chat.id, user_id=user.id, error=str(exc))

    return False
