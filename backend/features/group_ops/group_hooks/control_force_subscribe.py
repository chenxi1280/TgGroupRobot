from __future__ import annotations

import html
from urllib.parse import urlparse

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from backend.features.automation.services.scheduled_message_service import ScheduledMessageService
from backend.features.group_ops.group_hooks.common import _schedule_message_delete
from backend.features.moderation.services.user_action_runtime import (
    execute_user_action,
    notify_user_action_failure,
)
from backend.shared.services.formatters import format_user_display_name

log = structlog.get_logger(__name__)

_FORCE_SUBSCRIBE_MUTE_SECONDS = 600
_DEFAULT_WARNING_DELETE_SECONDS = 60
_BUTTON_TEXT_LENGTH = 64


def _numeric_target(raw: str) -> int | None:
    numeric = raw[1:] if raw.startswith("-") else raw
    return int(raw) if numeric.isdigit() else None


def _username_target(raw: str) -> str | None:
    if not raw.startswith("@") or len(raw) <= 1:
        return None
    if "/" in raw or "?" in raw:
        return None
    return raw


def _public_target_path(raw: str) -> str | None:
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {"t.me", "www.t.me"}:
        return None
    if parsed.query or parsed.fragment:
        return None
    path = parsed.path.strip("/")
    if not path or "/" in path or path.startswith("+") or path == "joinchat":
        return None
    return path


def _normalize_force_subscribe_target(value: str | int | None) -> str | int | None:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    numeric = _numeric_target(raw)
    if numeric is not None:
        return numeric
    username = _username_target(raw)
    if username is not None:
        return username
    path = _public_target_path(raw)
    return f"@{path}" if path else None


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


def _target_shape_diagnostic(target_chat, index: int) -> str | None:
    if getattr(target_chat, "type", None) not in {"channel", "group", "supergroup"}:
        return f"绑定目标{index}不是频道/群组，请重新绑定公开频道/群组。"
    if not str(getattr(target_chat, "username", "") or "").strip():
        return f"绑定目标{index}没有公开用户名，无法生成关注按钮。"
    return None


async def _bot_membership_diagnostic(bot, *, target, bot_id: int | None, index: int) -> str | None:
    if bot_id is None or not hasattr(bot, "get_chat_member"):
        return None
    try:
        bot_member = await bot.get_chat_member(chat_id=target, user_id=bot_id)
    except Exception as exc:
        log.warning("force_subscribe_bot_member_lookup_failed", target=target, bot_id=bot_id, error=str(exc))
        return f"绑定目标{index}无法确认机器人权限，请重新检查目标频道/群组。"
    if getattr(bot_member, "status", None) not in {"administrator", "creator"}:
        return f"绑定目标{index}机器人不是管理员，可能无法稳定校验订阅。"
    return None


async def _diagnose_force_subscribe_target(bot, *, raw_target, target, bot_id: int | None, index: int) -> str | None:
    if target is None or not _is_public_force_subscribe_target(raw_target):
        return f"绑定目标{index}格式无效，请重新绑定公开频道/群组的 @用户名。"
    if bot is None or not hasattr(bot, "get_chat"):
        return f"绑定目标{index}暂时无法检查机器人权限。"
    try:
        target_chat = await bot.get_chat(chat_id=target)
    except Exception as exc:
        log.warning("force_subscribe_target_lookup_failed", target=target, error=str(exc))
        return f"绑定目标{index}机器人无法访问，请确认机器人已加入并有权限。"
    shape_issue = _target_shape_diagnostic(target_chat, index)
    if shape_issue is not None:
        return shape_issue
    return await _bot_membership_diagnostic(bot, target=target, bot_id=bot_id, index=index)


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
        issue = await _diagnose_force_subscribe_target(
            bot,
            raw_target=raw_target,
            target=target,
            bot_id=bot_id,
            index=index,
        )
        if issue is not None:
            diagnostics.append(issue)
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
    return InlineKeyboardButton(text[:_BUTTON_TEXT_LENGTH], url=url)


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

    if fail_open:
        text = (
            "⚠️ 强制订阅配置异常，已临时跳过强制订阅校验，避免误伤已关注用户。\n"
            "普通成员仍会继续进入违禁词/垃圾防护检测；管理员和白名单不触发违禁词。\n"
            "请管理员重新绑定公开频道/群组的 @用户名，确保能生成关注按钮。"
        )
    else:
        text = (
            "⚠️ 强制订阅部分目标配置异常，已跳过这些异常目标。\n"
            "普通成员仍会继续进入违禁词/垃圾防护检测；管理员和白名单不触发违禁词。\n"
            "请管理员重新绑定公开频道/群组的 @用户名，确保能生成关注按钮。"
        )
    await notify_user_action_failure(
        context,
        chat_id=chat_id,
        feature="强制订阅配置",
        detail=text,
        failures=issue_reasons,
    )


def _is_force_subscribe_member(member) -> bool:
    status = getattr(member, "status", None)
    if status in {"left", "kicked"}:
        return False
    if status == "restricted" and hasattr(member, "is_member"):
        return bool(getattr(member, "is_member"))
    return True


def _custom_force_subscribe_markup(settings) -> InlineKeyboardMarkup | None:
    custom_enabled = bool(getattr(settings, "force_subscribe_custom_buttons_enabled", False))
    custom_buttons = getattr(settings, "force_subscribe_buttons", None) or []
    if not custom_enabled or not custom_buttons:
        return None
    normalized = ScheduledMessageService.normalize_buttons_config(custom_buttons)
    keyboard = [[InlineKeyboardButton(btn["text"], url=btn["url"]) for btn in row] for row in normalized]
    return InlineKeyboardMarkup(keyboard) if keyboard else None


async def _bound_force_subscribe_markup(context: ContextTypes.DEFAULT_TYPE, settings) -> InlineKeyboardMarkup | None:
    values = (
        getattr(settings, "force_subscribe_bound_channel_1", None),
        getattr(settings, "force_subscribe_bound_channel_2", None),
    )
    resolved = [await _build_resolved_force_subscribe_channel_button(context, value) for value in values]
    buttons = [button for button in resolved if button is not None]
    return InlineKeyboardMarkup([[button] for button in buttons]) if buttons else None


async def _build_force_subscribe_markup(context: ContextTypes.DEFAULT_TYPE, settings) -> InlineKeyboardMarkup | None:
    try:
        custom_markup = _custom_force_subscribe_markup(settings)
    except Exception as exc:
        log.warning("force_subscribe_custom_buttons_invalid", error=str(exc))
        custom_markup = None
    return custom_markup or await _bound_force_subscribe_markup(context, settings)


def _unchecked_diagnostic(configured_target, target, *, reason: str, error: str | None = None) -> dict[str, object]:
    diagnostic: dict[str, object] = {
        "target": configured_target,
        "normalized_target": target,
        "subscribed": False,
        "checked": False,
        "reason": reason,
    }
    if error is not None:
        diagnostic["error"] = error
    return diagnostic


async def _check_subscription_target(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    *,
    configured_target,
) -> tuple[bool | None, dict]:
    target = _normalize_force_subscribe_target(configured_target)
    if target is None or not _is_public_force_subscribe_target(configured_target):
        log.warning("force_subscribe_target_invalid", chat_id=chat.id, user_id=user.id, target=configured_target)
        return None, _unchecked_diagnostic(configured_target, target, reason="invalid_public_target")
    try:
        member = await context.bot.get_chat_member(chat_id=target, user_id=user.id)
    except Exception as exc:
        log.warning(
            "force_subscribe_check_failed",
            chat_id=chat.id,
            user_id=user.id,
            target=configured_target,
            normalized_target=target,
            error=str(exc),
        )
        return None, _unchecked_diagnostic(configured_target, target, reason=type(exc).__name__, error=str(exc))
    subscribed = _is_force_subscribe_member(member)
    return subscribed, {
        "target": configured_target,
        "normalized_target": target,
        "checked": True,
        "status": getattr(member, "status", None),
        "is_member": getattr(member, "is_member", None),
        "subscribed": subscribed,
    }


async def _collect_subscription_checks(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    *,
    targets: list,
) -> tuple[list[bool], list[dict]]:
    subscribed_results: list[bool] = []
    diagnostics: list[dict] = []
    for configured_target in targets:
        subscribed, diagnostic = await _check_subscription_target(
            context,
            chat,
            user,
            configured_target=configured_target,
        )
        diagnostics.append(diagnostic)
        if subscribed is not None:
            subscribed_results.append(subscribed)
    return subscribed_results, diagnostics


async def _apply_force_subscribe_action(context: ContextTypes.DEFAULT_TYPE, chat, user, *, message, action: str) -> None:
    if action in {"delete_and_warn", "delete_only"}:
        await execute_user_action(
            context,
            feature="强制订阅",
            chat_id=chat.id,
            user_id=user.id,
            action="none",
            detail="用户未完成强制订阅，删除发言",
            message=message,
            delete_message=True,
        )
    if action == "mute":
        await execute_user_action(
            context,
            feature="强制订阅",
            chat_id=chat.id,
            user_id=user.id,
            action="mute",
            detail="用户未完成强制订阅，临时禁言",
            message=message,
            mute_seconds=_FORCE_SUBSCRIBE_MUTE_SECONDS,
        )


def _force_subscribe_guide_text(settings, user) -> str:
    template = getattr(settings, "force_subscribe_guide_text", None) or "{member}，您需要关注指定频道/群组后才能发言。"
    user_label = html.escape(format_user_display_name(user, user.id))
    return template.replace("{member}", user_label).replace("{userid}", str(user.id)).replace("{nickname}", user_label)


async def _send_force_subscribe_guide(context: ContextTypes.DEFAULT_TYPE, chat, *, text: str, markup, settings):
    cover_type = getattr(settings, "force_subscribe_cover_media_type", None)
    cover_file_id = getattr(settings, "force_subscribe_cover_file_id", None)
    if cover_type == "photo" and cover_file_id:
        return await context.bot.send_photo(
            chat.id, photo=cover_file_id, caption=text, reply_markup=markup, parse_mode="HTML"
        )
    if cover_type == "video" and cover_file_id:
        return await context.bot.send_video(
            chat.id, video=cover_file_id, caption=text, reply_markup=markup, parse_mode="HTML"
        )
    return await context.bot.send_message(chat.id, text, reply_markup=markup, parse_mode="HTML")


async def _warn_unsubscribed_user(context: ContextTypes.DEFAULT_TYPE, chat, user, *, settings) -> None:
    text = _force_subscribe_guide_text(settings, user)
    markup = await _build_force_subscribe_markup(context, settings)
    try:
        sent = await _send_force_subscribe_guide(context, chat, text=text, markup=markup, settings=settings)
        delete_after = int(
            getattr(settings, "force_subscribe_delete_warn_after_seconds", _DEFAULT_WARNING_DELETE_SECONDS)
            or _DEFAULT_WARNING_DELETE_SECONDS
        )
        if delete_after > 0:
            _schedule_message_delete(context, sent, delete_after, name="group_hooks.force_subscribe_warn_delete")
    except Exception as exc:
        log.warning("force_subscribe_warn_failed", chat_id=chat.id, user_id=user.id, error=str(exc))


async def _check_force_subscribe(
    context: ContextTypes.DEFAULT_TYPE,
    chat,
    user,
    *, message,
    settings,
) -> bool:
    if not bool(getattr(settings, "force_subscribe_enabled", False)):
        return True
    configured_targets = [target for target in (
        getattr(settings, "force_subscribe_bound_channel_1", None),
        getattr(settings, "force_subscribe_bound_channel_2", None),
    ) if target]
    if not configured_targets:
        return True
    subscribed_results, diagnostics = await _collect_subscription_checks(
        context,
        chat,
        user,
        targets=configured_targets,
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
    await _apply_force_subscribe_action(context, chat, user, message=message, action=action)
    if action in {"delete_and_warn", "warn_only", "mute"}:
        await _warn_unsubscribed_user(context, chat, user, settings=settings)
    return False
