from __future__ import annotations

import datetime as dt
import html
from urllib.parse import urlparse

import structlog
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.group_ops.group_hooks.common import _schedule_message_delete
from backend.shared.services.formatters import format_user_display_name

log = structlog.get_logger(__name__)

FORCE_SUBSCRIBE_CONFIG_NOTIFY_SECONDS = 300


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


def _is_public_force_subscribe_target(value: str | int | None) -> bool:
    if not isinstance(value, str):
        return False
    raw = value.strip()
    if raw.startswith("@"):
        return _normalize_force_subscribe_target(raw) is not None
    parsed = urlparse(raw)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.lower() in {"t.me", "www.t.me"}
        and not parsed.query
        and not parsed.fragment
        and bool(parsed.path.strip("/"))
        and "/" not in parsed.path.strip("/")
        and not parsed.path.strip("/").startswith("+")
        and parsed.path.strip("/") != "joinchat"
    )


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
    if target_chat is not None:
        username = str(target_chat.username or "").strip()
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
    title = str(target_chat.title or "").strip()
    if title:
        return title
    username = str(target_chat.username or "").strip()
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


async def diagnose_force_subscribe_targets(context: ContextTypes.DEFAULT_TYPE, settings) -> list[str]:
    diagnostics: list[str] = []
    bot = getattr(context, "bot", None)
    bot_id = getattr(bot, "id", None)
    for index, raw_target in enumerate(
        (
            getattr(settings, "force_subscribe_bound_channel_1", None),
            getattr(settings, "force_subscribe_bound_channel_2", None),
        ),
        start=1,
    ):
        if not raw_target:
            continue
        target = _normalize_force_subscribe_target(raw_target)
        if target is None or not _is_public_force_subscribe_target(raw_target):
            diagnostics.append(f"绑定目标{index}格式无效，请重新绑定公开频道/群组的 @用户名。")
            continue
        if bot is None or not hasattr(bot, "get_chat"):
            diagnostics.append(f"绑定目标{index}暂时无法检查机器人权限。")
            continue
        try:
            target_chat = await bot.get_chat(chat_id=target)
        except Exception:
            diagnostics.append(f"绑定目标{index}机器人无法访问，请确认机器人已加入并有权限。")
            continue
        if getattr(target_chat, "type", None) not in {"channel", "group", "supergroup"}:
            diagnostics.append(f"绑定目标{index}不是频道/群组，请重新绑定公开频道/群组。")
            continue
        if not str(getattr(target_chat, "username", "") or "").strip():
            diagnostics.append(f"绑定目标{index}没有公开用户名，无法生成关注按钮。")
            continue
        if bot_id is None or not hasattr(bot, "get_chat_member"):
            continue
        try:
            bot_member = await bot.get_chat_member(chat_id=target, user_id=bot_id)
        except Exception:
            diagnostics.append(f"绑定目标{index}无法确认机器人权限，请重新检查目标频道/群组。")
            continue
        if getattr(bot_member, "status", None) not in {"administrator", "creator"}:
            diagnostics.append(f"绑定目标{index}机器人不是管理员，可能无法稳定校验订阅。")
    return diagnostics


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
    if not _is_public_force_subscribe_target(value):
        return None
    fallback = _force_subscribe_target_fallback_label(value)
    target_chat = await _resolve_force_subscribe_target_chat(context, value)
    label = _force_subscribe_label_from_chat(target_chat, fallback) if target_chat is not None else fallback
    return _build_force_subscribe_channel_button(value, label=label, target_chat=target_chat)


async def _notify_force_subscribe_config_issue(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    diagnostics: list[dict[str, object]],
    *,
    fail_open: bool,
) -> None:
    issue_reasons = [
        str(item.get("reason") or "unknown")
        for item in diagnostics
        if not bool(item.get("checked"))
    ]
    if not issue_reasons:
        return

    now = dt.datetime.now(dt.UTC)
    bot_data = getattr(getattr(context, "application", None), "bot_data", None)
    cache_key = (chat_id, tuple(sorted(issue_reasons)))
    if isinstance(bot_data, dict):
        notify_cache = bot_data.setdefault("_force_subscribe_config_issue_notified_at", {})
        last_notified = notify_cache.get(cache_key)
        if isinstance(last_notified, dt.datetime):
            elapsed = (now - last_notified).total_seconds()
            if elapsed < FORCE_SUBSCRIBE_CONFIG_NOTIFY_SECONDS:
                return
        notify_cache[cache_key] = now

    if fail_open:
        text = (
            "⚠️ 强制订阅配置异常，已临时放行本次发言，避免误伤已关注用户。\n"
            "请管理员重新绑定公开频道/群组的 @用户名，确保能生成关注按钮。"
        )
    else:
        text = (
            "⚠️ 强制订阅部分目标配置异常，已跳过这些异常目标。\n"
            "请管理员重新绑定公开频道/群组的 @用户名，确保能生成关注按钮。"
        )
    try:
        await context.bot.send_message(chat_id=chat_id, text=text)
        log.warning(
            "force_subscribe_config_issue_notified",
            chat_id=chat_id,
            diagnostics=diagnostics,
        )
    except Exception as exc:
        log.warning(
            "force_subscribe_config_issue_notify_failed",
            chat_id=chat_id,
            diagnostics=diagnostics,
            error=str(exc),
        )


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
    diagnostics: list[dict[str, object]] = []
    for configured_target in configured_targets:
        target = _normalize_force_subscribe_target(configured_target)
        if target is None or not _is_public_force_subscribe_target(configured_target):
            diagnostics.append(
                {
                    "target": configured_target,
                    "normalized_target": target,
                    "subscribed": False,
                    "checked": False,
                    "reason": "invalid_public_target",
                }
            )
            log.warning(
                "force_subscribe_target_invalid",
                chat_id=chat.id,
                user_id=user.id,
                target=configured_target,
            )
            continue
        try:
            member = await context.bot.get_chat_member(chat_id=target, user_id=user.id)
            subscribed = _is_force_subscribe_member(member)
            subscribed_results.append(subscribed)
            diagnostics.append(
                {
                    "target": configured_target,
                    "normalized_target": target,
                    "checked": True,
                    "status": getattr(member, "status", None),
                    "is_member": getattr(member, "is_member", None),
                    "subscribed": subscribed,
                }
            )
        except Exception as exc:
            diagnostics.append(
                {
                    "target": configured_target,
                    "normalized_target": target,
                    "subscribed": False,
                    "checked": False,
                    "reason": type(exc).__name__,
                    "error": str(exc),
                }
            )
            log.warning(
                "force_subscribe_check_failed",
                chat_id=chat.id,
                user_id=user.id,
                target=configured_target,
                normalized_target=target,
                error=str(exc),
            )

    if not subscribed_results:
        await _notify_force_subscribe_config_issue(context, chat.id, diagnostics, fail_open=True)
        log.warning(
            "force_subscribe_skip_all_targets_invalid",
            chat_id=chat.id,
            user_id=user.id,
            diagnostics=diagnostics,
        )
        return True

    check_mode = getattr(settings, "force_subscribe_check_mode", "all")
    await _notify_force_subscribe_config_issue(context, chat.id, diagnostics, fail_open=False)
    subscribed = all(subscribed_results) if check_mode == "all" else any(subscribed_results)
    log.info(
        "force_subscribe_check_result",
        chat_id=chat.id,
        user_id=user.id,
        check_mode=check_mode,
        subscribed=subscribed,
        diagnostics=diagnostics,
    )
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
        user_label = html.escape(format_user_display_name(user, user.id))
        text = (
            guide_text
            .replace("{member}", user_label)
            .replace("{userid}", str(user.id))
            .replace("{nickname}", user_label)
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
