from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Iterable

import structlog
from telegram.ext import ContextTypes

from backend.shared.services.action_executor import ActionExecutor
from backend.shared.services.permission_service import get_bot_admin_ids
_MAX_ADMIN_TARGETS = 5


log = structlog.get_logger(__name__)

USER_ACTION_DIAGNOSTIC_SECONDS = 300


@dataclass(frozen=True)
class UserActionResult:
    feature: str
    matched: bool = True
    stopped: bool = True
    delete_requested: bool = False
    delete_applied: bool = False
    punishment_requested: bool = False
    punishment_applied: bool = False
    action: str = "none"
    failures: tuple[str, ...] = field(default_factory=tuple)

    @property
    def applied(self) -> bool:
        return self.delete_applied or self.punishment_applied

    @property
    def failed(self) -> bool:
        return bool(self.failures)


def _context_chat_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    chat_data = getattr(context, "chat_data", None)
    if isinstance(chat_data, dict):
        value = chat_data.get("chat_id")
        if isinstance(value, int):
            return value
    return None


def _diagnostic_cache(context: ContextTypes.DEFAULT_TYPE) -> dict:
    bot_data = getattr(getattr(context, "application", None), "bot_data", None)
    if isinstance(bot_data, dict):
        return bot_data.setdefault("_user_action_diagnostic_notified_at", {})
    return {}


async def _resolve_admin_targets(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> list[int]:
    targets = sorted(get_bot_admin_ids(context))
    if targets:
        return targets[:5]

    bot = getattr(context, "bot", None)
    if bot is None or not hasattr(bot, "get_chat_administrators"):
        return []
    try:
        admins = await bot.get_chat_administrators(chat_id=chat_id)
    except Exception as exc:
        log.warning("user_action_admin_resolve_failed", chat_id=chat_id, error=str(exc))
        return []

    resolved: list[int] = []
    for member in admins:
        user = getattr(member, "user", None)
        user_id = getattr(user, "id", None)
        if isinstance(user_id, int) and user_id not in resolved:
            resolved.append(user_id)
        if len(resolved) >= _MAX_ADMIN_TARGETS:
            break
    return resolved


def _failure_text(failures: Iterable[str]) -> str:
    return "；".join(str(item) for item in failures if str(item).strip())


def _notification_is_recent(cache: dict, cache_key: tuple, now: dt.datetime) -> bool:
    last_notified = cache.get(cache_key)
    if not isinstance(last_notified, dt.datetime):
        return False
    return (now - last_notified).total_seconds() < USER_ACTION_DIAGNOSTIC_SECONDS


def _failure_notification_text(*, chat_id: int, feature: str, detail: str, failure_text: str) -> str:
    return (
        f"⚠️ {feature}已命中，但用户处置动作没有成功执行。\n"
        f"群组：{chat_id}\n"
        f"原因：{failure_text}\n"
        f"说明：{detail}\n"
        "请检查机器人是否仍是管理员，并拥有删除消息/禁言/封禁权限。"
    )


async def _send_failure_notifications(context: ContextTypes.DEFAULT_TYPE, targets: list[int], *, text: str, chat_id: int, feature: str) -> int:
    delivered = 0
    for admin_id in targets:
        try:
            await context.bot.send_message(chat_id=admin_id, text=text)
            delivered += 1
        except Exception as exc:
            log.warning(
                "user_action_failure_notify_failed",
                chat_id=chat_id,
                admin_id=admin_id,
                feature=feature,
                error=str(exc),
            )
    return delivered


async def notify_user_action_failure(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    feature: str,
    detail: str,
    failures: Iterable[str],
) -> None:
    failure_text = _failure_text(failures)
    if not failure_text:
        return
    cache = _diagnostic_cache(context)
    cache_key = (chat_id, feature, failure_text)
    now = dt.datetime.now(dt.UTC)
    if _notification_is_recent(cache, cache_key, now):
        return
    targets = await _resolve_admin_targets(context, chat_id)
    if not targets:
        log.warning(
            "user_action_failure_no_admin_target",
            chat_id=chat_id,
            feature=feature,
            detail=detail,
            failures=failure_text,
        )
        return
    text = _failure_notification_text(chat_id=chat_id, feature=feature, detail=detail, failure_text=failure_text)
    delivered = await _send_failure_notifications(
        context,
        targets,
        text=text,
        chat_id=chat_id,
        feature=feature,
    )
    if delivered:
        cache[cache_key] = now
        log.warning(
            "user_action_failure_notified",
            chat_id=chat_id,
            feature=feature,
            detail=detail,
            failures=failure_text,
            delivered=delivered,
        )


async def _delete_with_executor(context: ContextTypes.DEFAULT_TYPE, *, chat_id: int, message_id, feature: str) -> tuple[bool, list[str]]:
    if message_id is None:
        return False, ["missing_message_id"]
    failures: list[str] = []
    try:
        result = await ActionExecutor.delete_many(context, chat_id=chat_id, message_ids=[int(message_id)])
        applied = bool(result.applied)
        if not applied:
            failures.append(result.detail or "delete_many_not_applied")
        return applied, failures
    except Exception as exc:
        log.warning(
            "user_action_delete_many_failed",
            chat_id=chat_id,
            message_id=message_id,
            feature=feature,
            error=str(exc),
        )
        return False, [str(exc)]


async def _delete_with_message(message, *, chat_id: int, message_id, feature: str) -> tuple[bool, list[str]]:
    if not hasattr(message, "delete"):
        return False, []
    try:
        await message.delete()
        log.warning(
            "user_action_delete_fallback_succeeded",
            chat_id=chat_id,
            message_id=message_id,
            feature=feature,
        )
        return True, []
    except Exception as exc:
        log.warning(
            "user_action_delete_fallback_failed",
            chat_id=chat_id,
            message_id=message_id,
            feature=feature,
            error=str(exc),
        )
        return False, [str(exc)]


async def _report_action_failures(
    context: ContextTypes.DEFAULT_TYPE,
    failures: list[str],
    *,
    chat_id: int,
    feature: str,
    detail: str,
) -> None:
    if not failures:
        return
    await notify_user_action_failure(
        context,
        chat_id=chat_id,
        feature=feature,
        detail=detail,
        failures=failures,
    )


async def delete_message_safely(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    message,
    feature: str,
    detail: str,
) -> UserActionResult:
    message_id = getattr(message, "message_id", None)
    delete_applied, failures = await _delete_with_executor(
        context,
        chat_id=chat_id,
        message_id=message_id,
        feature=feature,
    )
    if not delete_applied:
        fallback_applied, fallback_failures = await _delete_with_message(
            message,
            chat_id=chat_id,
            message_id=message_id,
            feature=feature,
        )
        if fallback_applied:
            delete_applied, failures = True, []
        else:
            failures = [*failures, *fallback_failures]
    await _report_action_failures(context, failures, chat_id=chat_id, feature=feature, detail=detail)

    return UserActionResult(
        feature=feature,
        delete_requested=True,
        delete_applied=delete_applied,
        action="delete",
        failures=tuple(failures),
    )


async def _execute_delete_request(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    requested: bool,
    chat_id: int,
    message,
    message_id: int | None,
    feature: str,
    detail: str,
) -> tuple[bool, list[str]]:
    if not requested:
        return False, []
    if message is not None:
        result = await delete_message_safely(
            context,
            chat_id=chat_id,
            message=message,
            feature=feature,
            detail=detail,
        )
        return result.delete_applied, list(result.failures)
    try:
        result = await ActionExecutor.delete_many(
            context,
            chat_id=chat_id,
            message_ids=[message_id] if message_id is not None else [],
        )
        failures = [] if result.applied else [result.detail or "delete_not_applied"]
        return bool(result.applied), failures
    except Exception as exc:
        return False, [str(exc)]


async def _execute_punishment(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    action: str,
    chat_id: int,
    user_id: int,
    actor_user_id: int | None,
    message_id: int | None,
    mute_seconds: int | None,
    sender_chat_id: int | None,
    detail: str,
    feature: str,
) -> tuple[bool, list[str]]:
    if action in {"", "none", "noop", "delete"}:
        return False, []
    try:
        result = await ActionExecutor.execute(
            context,
            action=action,
            chat_id=chat_id,
            user_id=user_id,
            actor_user_id=actor_user_id,
            message_id=message_id,
            mute_seconds=mute_seconds,
            sender_chat_id=sender_chat_id,
            reason=detail,
        )
        failures = [] if result.applied else [result.detail or f"{action}_not_applied"]
        return bool(result.applied), failures
    except Exception as exc:
        log.warning(
            "user_action_punishment_failed",
            chat_id=chat_id,
            user_id=user_id,
            action=action,
            feature=feature,
            error=str(exc),
        )
        return False, [str(exc)]


async def execute_user_action(
    context: ContextTypes.DEFAULT_TYPE,
    *, feature: str, chat_id: int, user_id: int, action: str = "none", detail: str,
    message=None, message_id: int | None = None, delete_message: bool = False,
    mute_seconds: int | None = None, actor_user_id: int | None = None,
    sender_chat_id: int | None = None, raise_on_failure: bool = False,
) -> UserActionResult:
    normalized_action = (action or "none").strip().lower()
    target_message_id = message_id if message_id is not None else getattr(message, "message_id", None)
    delete_applied, delete_failures = await _execute_delete_request(
        context,
        requested=delete_message,
        chat_id=chat_id,
        message=message,
        message_id=message_id,
        feature=feature,
        detail=detail,
    )
    punishment_applied, punishment_failures = await _execute_punishment(
        context,
        action=normalized_action,
        chat_id=chat_id,
        user_id=user_id,
        actor_user_id=actor_user_id,
        message_id=target_message_id,
        mute_seconds=mute_seconds,
        sender_chat_id=sender_chat_id,
        detail=detail,
        feature=feature,
    )
    failures = [*delete_failures, *punishment_failures]

    await _report_action_failures(context, failures, chat_id=chat_id, feature=feature, detail=detail)
    result = UserActionResult(
        feature=feature,
        delete_requested=bool(delete_message),
        delete_applied=delete_applied,
        punishment_requested=normalized_action not in {"", "none", "noop", "delete"},
        punishment_applied=punishment_applied,
        action=normalized_action or "none",
        failures=tuple(failures),
    )
    if raise_on_failure and result.failed:
        raise RuntimeError("; ".join(result.failures))
    return result


async def restrict_user_safely(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    feature: str,
    chat_id: int,
    user_id: int,
    permissions,
    detail: str,
    until_date=None,
    raise_on_failure: bool = False,
) -> UserActionResult:
    failures: list[str] = []
    try:
        kwargs = {"chat_id": chat_id, "user_id": user_id, "permissions": permissions}
        if until_date is not None:
            kwargs["until_date"] = until_date
        await context.bot.restrict_chat_member(**kwargs)
        punishment_applied = True
    except Exception as exc:
        punishment_applied = False
        failures.append(str(exc))
        log.warning(
            "user_action_restrict_failed",
            chat_id=chat_id,
            user_id=user_id,
            feature=feature,
            error=str(exc),
        )
        await notify_user_action_failure(
            context,
            chat_id=chat_id,
            feature=feature,
            detail=detail,
            failures=failures,
        )

    result = UserActionResult(
        feature=feature,
        punishment_requested=True,
        punishment_applied=punishment_applied,
        action="mute",
        failures=tuple(failures),
    )
    if raise_on_failure and result.failed:
        raise RuntimeError("; ".join(result.failures))
    return result


async def execute_group_permission_action(
    context: ContextTypes.DEFAULT_TYPE,
    *,
    chat_id: int,
    permissions,
    feature: str,
    detail: str,
) -> UserActionResult:
    failures: list[str] = []
    try:
        await context.bot.set_chat_permissions(chat_id=chat_id, permissions=permissions)
        applied = True
    except Exception as exc:
        applied = False
        failures.append(str(exc))
        log.warning(
            "group_permission_action_failed",
            chat_id=chat_id,
            feature=feature,
            error=str(exc),
        )
        await notify_user_action_failure(
            context,
            chat_id=chat_id,
            feature=feature,
            detail=detail,
            failures=failures,
        )

    return UserActionResult(
        feature=feature,
        punishment_requested=True,
        punishment_applied=applied,
        action="group_permissions",
        failures=tuple(failures),
    )
